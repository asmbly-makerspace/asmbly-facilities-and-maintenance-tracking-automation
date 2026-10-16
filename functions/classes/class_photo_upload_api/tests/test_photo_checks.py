import random
import struct
import time
from pathlib import Path
from typing import Any

import pytest

from functions.classes.class_photo_upload_api.photo_checks import (
    LOCATION_MESSAGE,
    MAX_EMBEDDED_IMAGES,
    MAX_HEADER_SEGMENTS,
    MAX_PHOTO_BYTES,
    NOT_JPEG_MESSAGE,
    UNREADABLE_JPEG_MESSAGE,
    JpegInfo,
    NotJpegError,
    UnreadableJpegError,
    check_photo,
    ratio_text,
    read_jpeg_info,
)
from functions.classes.class_photo_upload_api.tests.jpeg_builder import (
    SOI,
    make_jpeg,
    segment,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FIXTURES = Path(__file__).parent / "fixtures"


def wrong_ratio(width: int, height: int, ratio: str) -> str:
    return (
        f"This photo is {width}×{height}, which is {ratio}. "
        "Class photos must be 3:2, for example 1500×1000. Crop it and try again."
    )


def not_landscape(width: int, height: int, ratio: str) -> str:
    return (
        f"This photo is {width}×{height}, which is {ratio} and not landscape. "
        "Class photos must be 3:2 landscape, for example 1500×1000. Crop it and try again."
    )


def test_accepts_exact_3_2() -> None:
    assert check_photo(make_jpeg(1500, 1000)) is None


@pytest.mark.parametrize("width, height", [(2000, 1334), (4000, 2667), (1515, 1000), (1485, 1000)])
def test_accepts_within_tolerance(width: int, height: int) -> None:
    assert check_photo(make_jpeg(width, height)) is None


@pytest.mark.parametrize(
    "width, height, ratio",
    [(1520, 1000, "1.52:1"), (1480, 1000, "1.48:1"), (1516, 1000, "1.52:1")],
)
def test_refuses_outside_tolerance(width: int, height: int, ratio: str) -> None:
    assert check_photo(make_jpeg(width, height)) == wrong_ratio(width, height, ratio)


def test_refuses_4_3_with_example_message() -> None:
    assert check_photo(make_jpeg(4000, 3000)) == (
        "This photo is 4000×3000, which is 4:3. Class photos must be 3:2, "
        "for example 1500×1000. Crop it and try again."
    )


def test_refuses_portrait() -> None:
    assert check_photo(make_jpeg(1000, 1500)) == not_landscape(1000, 1500, "2:3")


def test_refuses_square() -> None:
    assert check_photo(make_jpeg(1000, 1000)) == not_landscape(1000, 1000, "1:1")


@pytest.mark.parametrize("byte_order", ["II", "MM"])
@pytest.mark.parametrize("orientation", range(1, 9))
def test_orientation_swaps_size(orientation: int, byte_order: str) -> None:
    photo = make_jpeg(1500, 1000, orientation=orientation, byte_order=byte_order)

    assert read_jpeg_info(photo).orientation == orientation
    if orientation >= 5:
        assert check_photo(photo) == not_landscape(1000, 1500, "2:3")
    else:
        assert check_photo(photo) is None


@pytest.mark.parametrize("byte_order", ["II", "MM"])
def test_orientation_turns_portrait_to_landscape(byte_order: str) -> None:
    assert check_photo(make_jpeg(1000, 1500, orientation=6, byte_order=byte_order)) is None


def test_orientation_big_endian() -> None:
    info = read_jpeg_info(make_jpeg(1500, 1000, orientation=8, byte_order="MM"))

    assert info == JpegInfo(
        width=1500, height=1000, orientation=8, has_exif_gps=False, has_xmp_gps=False, has_embedded_gps=False
    )
    assert info.displayed_size == (1000, 1500)


@pytest.mark.parametrize("value", [0, 9, 0xFFFF])
def test_out_of_range_orientation_counts_as_1(value: int) -> None:
    assert read_jpeg_info(make_jpeg(1500, 1000, orientation=value)).orientation == 1


def test_missing_orientation_counts_as_1() -> None:
    assert read_jpeg_info(make_jpeg(1500, 1000)).orientation == 1


def test_refuses_png_bytes() -> None:
    assert check_photo(PNG_SIGNATURE + b"\x00\x00\x00\rIHDR" + b"\x00" * 64) == NOT_JPEG_MESSAGE


@pytest.mark.parametrize("data", [b"", b"\xff", b"\xff\xd8", b"GIF89a", b"\xff\xd8\x00\x00"])
def test_refuses_other_non_jpeg_bytes(data: bytes) -> None:
    assert check_photo(data) == NOT_JPEG_MESSAGE


def test_refuses_truncated_jpeg() -> None:
    photo = make_jpeg(1500, 1000)
    sof = photo.index(b"\xff\xc0")

    assert check_photo(photo[: sof + 6]) == UNREADABLE_JPEG_MESSAGE


def test_refuses_jpeg_without_sof() -> None:
    assert check_photo(make_jpeg(1500, 1000, sof_marker=None)) == UNREADABLE_JPEG_MESSAGE


@pytest.mark.parametrize("length", [b"\x00\x01", b"\x00\x00", b"\xff\xff"])
def test_refuses_bad_segment_length(length: bytes) -> None:
    photo = SOI + b"\xff\xe0" + length + b"JFIF" + make_jpeg(1500, 1000)[2:]

    assert check_photo(photo) == UNREADABLE_JPEG_MESSAGE


def test_refuses_missing_marker() -> None:
    photo = SOI + b"\xff\xe0\x00\x04ab" + b"\x00" + make_jpeg(1500, 1000)[2:]

    assert check_photo(photo) == UNREADABLE_JPEG_MESSAGE


def test_refuses_zero_size() -> None:
    assert check_photo(make_jpeg(0, 1000)) == UNREADABLE_JPEG_MESSAGE
    assert check_photo(make_jpeg(1500, 0)) == UNREADABLE_JPEG_MESSAGE


def test_refuses_short_frame_header() -> None:
    photo = SOI + segment(0xC0, b"\x08\x03\xe8") + segment(0xDA, b"\x00") + b"\xff\xd9"

    assert check_photo(photo) == UNREADABLE_JPEG_MESSAGE


def test_refuses_bad_tiff_byte_order() -> None:
    assert check_photo(make_jpeg(1500, 1000, orientation=1, byte_order="XX")) == UNREADABLE_JPEG_MESSAGE


@pytest.mark.parametrize("offset", [0, 4, 10_000])
def test_refuses_ifd_offset_out_of_range(offset: int) -> None:
    assert check_photo(make_jpeg(1500, 1000, orientation=1, ifd0_offset=offset)) == UNREADABLE_JPEG_MESSAGE


def test_refuses_bad_tiff_magic() -> None:
    photo = make_jpeg(1500, 1000, orientation=1).replace(b"II\x2a\x00", b"II\x2b\x00", 1)

    assert check_photo(photo) == UNREADABLE_JPEG_MESSAGE


def test_refuses_truncated_ifd_entries() -> None:
    exif = b"Exif\x00\x00II\x2a\x00\x08\x00\x00\x00\x05\x00" + b"\x00" * 12
    photo = SOI + segment(0xE1, exif) + make_jpeg(1500, 1000)[2:]

    assert check_photo(photo) == UNREADABLE_JPEG_MESSAGE


@pytest.mark.parametrize("sof_marker", [0xC2, 0xC1, 0xCF])
def test_reads_progressive_sof(sof_marker: int) -> None:
    info = read_jpeg_info(make_jpeg(3000, 2000, sof_marker=sof_marker))

    assert (info.width, info.height) == (3000, 2000)
    assert check_photo(make_jpeg(3000, 2000, sof_marker=sof_marker)) is None


def test_keeps_the_first_sof() -> None:
    photo = make_jpeg(1500, 1000)
    sos = photo.index(b"\xff\xda")
    second_sof = segment(0xC0, b"\x08\x03\xe8\x03\xe8\x01\x01\x11\x00")
    photo = photo[:sos] + second_sof + photo[sos:]

    assert read_jpeg_info(photo).displayed_size == (1500, 1000)


def test_skips_fill_bytes_and_standalone_markers() -> None:
    photo = SOI + b"\xff\xff\xff\x01" + b"\xff\xd0" + make_jpeg(1500, 1000)[2:]

    assert check_photo(photo) is None


def test_refuses_over_4_mb() -> None:
    photo = make_jpeg(1500, 1000, pad_to=MAX_PHOTO_BYTES + 1)

    assert len(photo) == MAX_PHOTO_BYTES + 1
    assert check_photo(photo) == (
        "This photo is 4.1 MB. Class photos must be 4 MB or less. "
        "Export it at a smaller size and try again."
    )


def test_accepts_exactly_4_mb() -> None:
    photo = make_jpeg(1500, 1000, pad_to=MAX_PHOTO_BYTES)

    assert len(photo) == MAX_PHOTO_BYTES
    assert check_photo(photo) is None


def test_size_is_rounded_up() -> None:
    photo = make_jpeg(1500, 1000, pad_to=5 * 1024 * 1024)

    assert check_photo(photo).startswith("This photo is 5.0 MB.")
    assert check_photo(photo + b"\x00").startswith("This photo is 5.1 MB.")


def test_refuses_exif_gps() -> None:
    photo = make_jpeg(1500, 1000, exif_gps=True)

    assert read_jpeg_info(photo).has_exif_gps
    assert check_photo(photo) == LOCATION_MESSAGE


@pytest.mark.parametrize("byte_order", ["II", "MM"])
def test_refuses_exif_gps_with_orientation(byte_order: str) -> None:
    photo = make_jpeg(1000, 1500, orientation=6, exif_gps=True, byte_order=byte_order)

    assert read_jpeg_info(photo).orientation == 6
    assert check_photo(photo) == LOCATION_MESSAGE


def test_refuses_xmp_gps() -> None:
    photo = make_jpeg(1500, 1000, xmp_gps=True)

    assert read_jpeg_info(photo).has_xmp_gps
    assert check_photo(photo) == LOCATION_MESSAGE


def test_refuses_xmp_gps_in_extended_chunk() -> None:
    photo = make_jpeg(1500, 1000, xmp_extended_chunks=[b'<rdf:Description exif:GPSLongitude="97,44.6W"/>'])

    assert check_photo(photo) == LOCATION_MESSAGE


def test_refuses_xmp_gps_split_across_extended_chunks() -> None:
    chunks = [b'<rdf:Description exif:GPSLat', b'itude="30,16.5N"/>']
    photo = make_jpeg(1500, 1000, xmp_extended_chunks=chunks)

    assert read_jpeg_info(photo).has_xmp_gps
    assert check_photo(photo) == LOCATION_MESSAGE


def test_accepts_plain_extended_xmp() -> None:
    photo = make_jpeg(1500, 1000, xmp_extended_chunks=[b"<dc:title>Wood", b"shop</dc:title>"])

    assert check_photo(photo) is None


def test_accepts_plain_xmp() -> None:
    photo = make_jpeg(1500, 1000, xmp_plain=True, orientation=1)

    assert read_jpeg_info(photo) == JpegInfo(
        width=1500, height=1000, orientation=1, has_exif_gps=False, has_xmp_gps=False, has_embedded_gps=False
    )
    assert check_photo(photo) is None


@pytest.mark.parametrize("byte_order", ["II", "MM"])
@pytest.mark.parametrize("ifd", ["ifd1", "exif"])
def test_refuses_gps_pointer_outside_ifd0(ifd: str, byte_order: str) -> None:
    photo = make_jpeg(1000, 1500, orientation=6, exif_gps=True, exif_gps_ifd=ifd, byte_order=byte_order)
    info = read_jpeg_info(photo)

    assert (info.orientation, info.has_exif_gps) == (6, True)
    assert check_photo(photo) == LOCATION_MESSAGE


def _exif_segment(tiff: bytes) -> bytes:
    return segment(0xE1, b"Exif\x00\x00" + tiff)


@pytest.mark.parametrize("next_offset", [4, 26, 10_000, 0xFFFFFFFF])
def test_ignores_ifd1_out_of_range(next_offset: int) -> None:
    # IFD0 with one orientation entry; its next-IFD offset points nowhere useful (26 is
    # IFD0 itself: read once, not again).
    tiff = b"II\x2a\x00\x08\x00\x00\x00" + struct.pack("<H", 1)
    tiff += struct.pack("<HHI", 0x0112, 3, 1) + b"\x06\x00\x00\x00" + struct.pack("<I", next_offset)
    photo = SOI + _exif_segment(tiff) + make_jpeg(1000, 1500)[2:]

    assert read_jpeg_info(photo).orientation == 6
    assert check_photo(photo) is None


def test_ignores_exif_sub_ifd_out_of_range() -> None:
    tiff = b"MM\x00\x2a\x00\x00\x00\x08" + struct.pack(">H", 1)
    tiff += struct.pack(">HHII", 0x8769, 4, 1, 5000) + struct.pack(">I", 0)
    photo = SOI + _exif_segment(tiff) + make_jpeg(1500, 1000)[2:]

    assert check_photo(photo) is None


def test_reads_partial_exif_sub_ifd() -> None:
    # The Exif sub-IFD says 50 entries but holds one whole entry: the GPS pointer.
    tiff = b"II\x2a\x00\x08\x00\x00\x00" + struct.pack("<H", 1)
    tiff += struct.pack("<HHII", 0x8769, 4, 1, 26) + struct.pack("<I", 0)
    tiff += struct.pack("<H", 50) + struct.pack("<HHII", 0x8825, 4, 1, 0)
    photo = SOI + _exif_segment(tiff) + make_jpeg(1500, 1000)[2:]

    assert check_photo(photo) == LOCATION_MESSAGE


def test_refuses_gps_in_image_after_eoi() -> None:
    photo = make_jpeg(1500, 1000, trailer=make_jpeg(320, 240, exif_gps=True))
    info = read_jpeg_info(photo)

    assert (info.has_exif_gps, info.has_xmp_gps, info.has_embedded_gps) == (False, False, True)
    assert check_photo(photo) == LOCATION_MESSAGE


@pytest.mark.parametrize(
    "embedded",
    [
        {"xmp_gps": True},
        {"xmp_extended_chunks": [b"GPSLong", b"itude"]},
        {"exif_gps": True, "exif_gps_ifd": "ifd1", "byte_order": "MM"},
    ],
)
def test_refuses_location_in_embedded_image(embedded: dict[str, Any]) -> None:
    photo = make_jpeg(1500, 1000, trailer=make_jpeg(640, 480, **embedded))

    assert check_photo(photo) == LOCATION_MESSAGE


def test_refuses_gps_in_second_of_several_embedded_images() -> None:
    trailer = make_jpeg(640, 480) + make_jpeg(160, 120, exif_gps=True)

    assert check_photo(make_jpeg(1500, 1000, trailer=trailer)) == LOCATION_MESSAGE


def test_refuses_xmp_gps_in_trailer_outside_any_image() -> None:
    trailer = b"motion photo video\x00" + b'<rdf:Description exif:GPSLatitude="30,16.5N"/>'

    assert check_photo(make_jpeg(1500, 1000, trailer=trailer)) == LOCATION_MESSAGE


def test_accepts_clean_embedded_images() -> None:
    trailer = make_jpeg(640, 480, orientation=1, xmp_plain=True) + make_jpeg(160, 120)
    photo = make_jpeg(1500, 1000, trailer=trailer)

    assert read_jpeg_info(photo).has_embedded_gps is False
    assert check_photo(photo) is None


def test_ignores_unreadable_embedded_image() -> None:
    trailer = b"\xff\xd8\xff\xe1\xff\xff" + b"\x00" * 16

    assert check_photo(make_jpeg(1500, 1000, trailer=trailer)) is None


def test_keeps_gps_read_before_embedded_image_breaks() -> None:
    broken = make_jpeg(640, 480, exif_gps=True)
    sof = broken.index(b"\xff\xc0")
    trailer = broken[:sof] + b"\xff\xe0\x00\x01"

    assert check_photo(make_jpeg(1500, 1000, trailer=trailer)) == LOCATION_MESSAGE


def test_embedded_image_limit() -> None:
    clean = make_jpeg(16, 16)
    at_limit = make_jpeg(1500, 1000, trailer=clean * MAX_EMBEDDED_IMAGES)
    over_limit = make_jpeg(1500, 1000, trailer=clean * (MAX_EMBEDDED_IMAGES + 1))

    assert check_photo(at_limit) is None
    assert check_photo(over_limit) == UNREADABLE_JPEG_MESSAGE


def test_header_segment_limit() -> None:
    def with_comments(count: int) -> bytes:
        return SOI + segment(0xFE, b"x") * count + make_jpeg(1500, 1000)[2:]

    # make_jpeg itself writes 2 segments (APP0, SOF) before SOS.
    assert check_photo(with_comments(MAX_HEADER_SEGMENTS - 3)) is None
    assert check_photo(with_comments(MAX_HEADER_SEGMENTS)) == UNREADABLE_JPEG_MESSAGE


def test_hostile_photo_is_checked_quickly() -> None:
    fill_run = SOI + b"\xff" * (MAX_PHOTO_BYTES // 2) + make_jpeg(1500, 1000)[2:]
    many_starts = make_jpeg(1500, 1000, trailer=b"\xff\xd8\xff\xfe\x00\x02" * (MAX_PHOTO_BYTES // 8))
    tiny_segments = SOI + segment(0xFE, b"") * (MAX_PHOTO_BYTES // 4 - 1)

    started = time.monotonic()
    assert check_photo(fill_run) is None
    assert check_photo(many_starts) == UNREADABLE_JPEG_MESSAGE
    assert check_photo(tiny_segments) == UNREADABLE_JPEG_MESSAGE
    assert time.monotonic() - started < 2


@pytest.mark.parametrize(
    "fixture, width, height, orientation, jpeg_starts",
    [
        # Canon EOS R5 through Photoshop Camera Raw: EXIF, XMP, IPTC, two thumbnails.
        ("asmbly_classes_3dprintingDefault_headers.bin", 2000, 1334, 1, 3),
        # GIMP 2.10 export: EXIF with Orientation 1 (TopLeft) and a thumbnail.
        ("asmbly_classes_PCBWay_Soldering_Activity_headers.bin", 1620, 1080, 1, 2),
        # No EXIF; XMP only.
        ("asmbly_classes_Addressable_LEDs_-_Make_a_Lantern_headers.bin", 1500, 1000, 1, 1),
    ],
)
def test_real_photo_headers(fixture: str, width: int, height: int, orientation: int, jpeg_starts: int) -> None:
    # Headers of real class images from asmbly-classes at bdf601b, cut 16 bytes into the
    # image data. Expected values from ImageMagick's identify on the whole file.
    photo = (FIXTURES / fixture).read_bytes()

    assert photo.count(b"\xff\xd8\xff") == jpeg_starts
    assert read_jpeg_info(photo) == JpegInfo(
        width=width,
        height=height,
        orientation=orientation,
        has_exif_gps=False,
        has_xmp_gps=False,
        has_embedded_gps=False,
    )
    assert check_photo(photo) is None


@pytest.mark.parametrize(
    "fixture",
    ["asmbly_classes_3dprintingDefault_headers.bin", "asmbly_classes_PCBWay_Soldering_Activity_headers.bin"],
)
def test_real_photo_with_gps_image_appended(fixture: str) -> None:
    photo = (FIXTURES / fixture).read_bytes() + b"\xff\xd9" + make_jpeg(320, 240, exif_gps=True)

    assert check_photo(photo) == LOCATION_MESSAGE


def test_ratio_is_checked_before_location() -> None:
    assert check_photo(make_jpeg(4000, 3000, exif_gps=True)) == wrong_ratio(4000, 3000, "4:3")


def test_size_is_checked_before_parsing() -> None:
    data = PNG_SIGNATURE + b"\x00" * MAX_PHOTO_BYTES

    assert check_photo(data).startswith("This photo is 4.1 MB.")


@pytest.mark.parametrize(
    "width, height, expected",
    [(4000, 3000, "4:3"), (1920, 1080, "16:9"), (1000, 1000, "1:1"), (1999, 1000, "2.00:1"), (1500, 1000, "3:2")],
)
def test_ratio_text(width: int, height: int, expected: str) -> None:
    assert ratio_text(width, height) == expected


_RANDOM = random.Random(73)
_RANDOM_BYTES = [_RANDOM.randbytes(_RANDOM.randint(0, 64)) for _ in range(200)]


@pytest.mark.parametrize("data", _RANDOM_BYTES)
def test_check_photo_never_raises(data: bytes) -> None:
    assert isinstance(check_photo(data), str)
    assert isinstance(check_photo(b"\xff\xd8\xff" + data), str)


_VALID = make_jpeg(
    1000,
    1500,
    orientation=6,
    exif_gps=True,
    xmp_gps=True,
    xmp_extended_chunks=[b"GPSAlt", b"itude"],
    trailer=make_jpeg(64, 48, exif_gps=True, exif_gps_ifd="exif", byte_order="MM"),
)


def _mutations() -> list[bytes]:
    rng = random.Random(106)
    cases = []
    for index in range(300):
        if index % 3 == 0:
            cases.append(_VALID[: rng.randint(0, len(_VALID) - 1)])
        elif index % 3 == 1:
            clean = make_jpeg(1500, 1000)
            junk = rng.randbytes(rng.randint(1, 64))
            cases.append(clean + junk + b"\xff\xd8\xff" + rng.randbytes(rng.randint(0, 64)))
        else:
            mutated = bytearray(_VALID)
            for _ in range(rng.randint(1, 4)):
                mutated[rng.randrange(len(mutated))] = rng.randrange(256)
            cases.append(bytes(mutated))
    return cases


@pytest.mark.parametrize("data", _mutations())
def test_mutated_jpeg_never_raises(data: bytes) -> None:
    result = check_photo(data)
    assert result is None or isinstance(result, str)
    try:
        read_jpeg_info(data)
    except (NotJpegError, UnreadableJpegError):
        pass
