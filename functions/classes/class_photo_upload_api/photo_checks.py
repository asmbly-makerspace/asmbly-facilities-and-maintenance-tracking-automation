"""Checks on a class photo, from its bytes alone.

Only the JPEG headers are read (ITU T.81 B.1.1 segment layout, the EXIF/TIFF IFDs,
and XMP APP1 segments), for the main image and for every other JPEG inside the file
(thumbnails, and the MPF images, gain maps and depth maps phones append after it); the
image itself is never decoded. "Location data" means GPS coordinates: place names
(IPTC City, XMP photoshop:City and the like) are not looked for. The messages are the ones
the upload page shows, so a person reads the same words whichever side finds the
problem.
"""

import math
import re
import struct
from dataclasses import dataclass, field

MAX_PHOTO_BYTES = 4 * 1024 * 1024
TARGET_RATIO = (3, 2)  # width:height
RATIO_TOLERANCE_PERCENT = 1  # abs(w / h - 1.5) / 1.5 <= 0.01, compared in integers
EXAMPLE_SIZE = "1500×1000"
RATIO_TERM_LIMIT = 32  # "4:3" when both terms are this small, else "1.33:1"
MAX_HEADER_SEGMENTS = 1000  # per image; real photos have a few dozen
MAX_EMBEDDED_IMAGES = 16  # JPEG starts after the first; phones write two or three

SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
XMP_IDS = (b"http://ns.adobe.com/xap/1.0/\x00", b"http://ns.adobe.com/xmp/extension/\x00")
XMP_GPS_PATTERN = re.compile(rb"GPS(Latitude|Longitude|Altitude|DestLatitude|DestLongitude)")

TOO_BIG_MESSAGE = (
    "This photo is {size:.1f} MB. Class photos must be 4 MB or less. "
    "Export it at a smaller size and try again."
)
NOT_JPEG_MESSAGE = "This file isn't a JPEG photo. Save or export it as a JPEG (.jpg) and try again."
UNREADABLE_JPEG_MESSAGE = "This JPEG couldn't be read. Export it again as a JPEG and try again."
WRONG_RATIO_MESSAGE = (
    "This photo is {width}×{height}, which is {ratio}. "
    "Class photos must be 3:2, for example {example}. Crop it and try again."
)
NOT_LANDSCAPE_MESSAGE = (
    "This photo is {width}×{height}, which is {ratio} and not landscape. "
    "Class photos must be 3:2 landscape, for example {example}. Crop it and try again."
)
LOCATION_MESSAGE = "This photo still has location data. Use the upload page, which removes it."

_EXIF_ID = b"Exif\x00\x00"
_XMP_EXTENSION_ID = XMP_IDS[1]
_XMP_EXTENSION_HEADER_LENGTH = 40  # GUID (32), full length (4), offset (4)
_TAG_ORIENTATION = 0x0112
_TAG_GPS_IFD = 0x8825
_TAG_EXIF_IFD = 0x8769
_JPEG_START = b"\xff\xd8\xff"
_FILL_BYTES = re.compile(rb"\xff+")
_TYPE_SHORT = 3
_MEBIBYTE = 1024 * 1024


class NotJpegError(ValueError):
    """The bytes don't start like a JPEG."""


class UnreadableJpegError(ValueError):
    """The bytes start like a JPEG, but its headers can't be read."""


@dataclass(frozen=True)
class JpegInfo:
    width: int  # as stored in the SOF segment
    height: int
    orientation: int  # 1..8; 1 when absent or out of range
    has_exif_gps: bool  # the EXIF has tag 0x8825 (IFD0, IFD1 or the Exif sub-IFD)
    has_xmp_gps: bool  # XMP GPS properties in an XMP segment, or anywhere after the headers
    has_embedded_gps: bool  # another JPEG in the file (thumbnail, MPF image) has either

    @property
    def has_location(self) -> bool:
        return self.has_exif_gps or self.has_xmp_gps or self.has_embedded_gps

    @property
    def displayed_size(self) -> tuple[int, int]:
        """Width and height after the orientation flag (5-8 swap them)."""
        if self.orientation >= 5:
            return self.height, self.width
        return self.width, self.height


def _ifd_entries(tiff: bytes, order: str, offset: int) -> list[tuple[int, int, int, int]]:
    """(tag, type, count, entry offset) for each whole entry of the IFD at ``offset``.

    An IFD whose count is out of range is read as far as it goes; an offset out of
    range gives no entries.
    """
    if offset < 8 or offset + 2 > len(tiff):
        return []
    (entry_count,) = struct.unpack(order + "H", tiff[offset : offset + 2])
    whole_entries = min(entry_count, (len(tiff) - offset - 2) // 12)
    entries = []
    for index in range(whole_entries):
        entry = offset + 2 + 12 * index
        tag, value_type, count = struct.unpack(order + "HHI", tiff[entry : entry + 8])
        entries.append((tag, value_type, count, entry))
    return entries


def _read_exif(tiff: bytes) -> tuple[int, bool]:
    """(orientation, has a GPS IFD pointer) from a TIFF block.

    Orientation is read from IFD0, which must be whole. The GPS IFD pointer (tag
    0x8825) belongs in IFD0; it is also looked for in IFD1 and the Exif sub-IFD, each
    read once, with no further pointers followed.
    """
    if len(tiff) < 8:
        raise UnreadableJpegError("EXIF header is truncated")
    if tiff[:2] == b"II":
        order = "<"
    elif tiff[:2] == b"MM":
        order = ">"
    else:
        raise UnreadableJpegError("EXIF byte order is unknown")
    magic, ifd0_offset = struct.unpack(order + "HI", tiff[2:8])
    if magic != 42:
        raise UnreadableJpegError("EXIF magic number is wrong")
    if ifd0_offset < 8 or ifd0_offset + 2 > len(tiff):
        raise UnreadableJpegError("EXIF IFD0 offset is out of range")
    (entry_count,) = struct.unpack(order + "H", tiff[ifd0_offset : ifd0_offset + 2])
    entries_end = ifd0_offset + 2 + 12 * entry_count
    if entries_end > len(tiff):
        raise UnreadableJpegError("EXIF IFD0 entries are truncated")

    orientation = 1
    has_gps = False
    other_ifds: list[int] = []
    if entries_end + 4 <= len(tiff):
        (ifd1_offset,) = struct.unpack(order + "I", tiff[entries_end : entries_end + 4])
        other_ifds.append(ifd1_offset)
    for tag, value_type, count, entry in _ifd_entries(tiff, order, ifd0_offset):
        if tag == _TAG_ORIENTATION and value_type == _TYPE_SHORT and count == 1:
            (value,) = struct.unpack(order + "H", tiff[entry + 8 : entry + 10])
            orientation = value if 1 <= value <= 8 else 1
        elif tag == _TAG_GPS_IFD:
            has_gps = True
        elif tag == _TAG_EXIF_IFD:
            (exif_ifd_offset,) = struct.unpack(order + "I", tiff[entry + 8 : entry + 12])
            other_ifds.append(exif_ifd_offset)

    for offset in set(other_ifds) - {ifd0_offset}:
        if any(tag == _TAG_GPS_IFD for tag, _, _, _ in _ifd_entries(tiff, order, offset)):
            has_gps = True
    return orientation, has_gps


def _extended_xmp_has_gps(chunks: list[bytes]) -> bool:
    """Joins extended XMP chunks by GUID and offset, and looks for GPS properties."""
    by_guid: dict[bytes, list[tuple[int, bytes]]] = {}
    for chunk in chunks:
        if len(chunk) < _XMP_EXTENSION_HEADER_LENGTH:
            continue
        guid = chunk[:32]
        (offset,) = struct.unpack(">I", chunk[36:40])
        by_guid.setdefault(guid, []).append((offset, chunk[_XMP_EXTENSION_HEADER_LENGTH:]))
    for parts in by_guid.values():
        joined = b"".join(data for _, data in sorted(parts, key=lambda part: part[0]))
        if XMP_GPS_PATTERN.search(joined):
            return True
    return False


@dataclass
class _Headers:
    """What one header walk found. Filled in as the walk goes, so a walk that fails
    part-way still reports what it read before the failure."""

    size: tuple[int, int] | None = None
    orientation: int | None = None
    has_exif_gps: bool = False
    has_xmp_gps: bool = False
    extended_xmp: list[bytes] = field(default_factory=list)
    end: int = 0  # the offset just after the SOS or EOI marker that ended the walk

    @property
    def has_gps(self) -> bool:
        return self.has_exif_gps or self.has_xmp_gps or _extended_xmp_has_gps(self.extended_xmp)


def _walk_headers(data: bytes, start: int, found: _Headers) -> None:
    """Walks the marker segments of the image whose SOI is at ``start``, up to its SOS.

    Raises ``UnreadableJpegError`` when a segment is cut short or malformed, or after
    ``MAX_HEADER_SEGMENTS`` segments.
    """
    end = len(data)
    position = start + 2
    for _ in range(MAX_HEADER_SEGMENTS):
        if position >= end or data[position] != 0xFF:
            raise UnreadableJpegError("expected a marker")
        fill = _FILL_BYTES.match(data, position)
        position = fill.end() if fill else position
        if position >= end:
            raise UnreadableJpegError("ended inside a marker")
        marker = data[position]
        position += 1
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if marker in (0xD9, 0xDA):
            found.end = position
            return
        if position + 2 > end:
            raise UnreadableJpegError("segment length is truncated")
        (length,) = struct.unpack(">H", data[position : position + 2])
        if length < 2 or position + length > end:
            raise UnreadableJpegError("segment length is out of range")
        payload = data[position + 2 : position + length]
        position += length

        if marker in SOF_MARKERS:
            if found.size is None:
                if len(payload) < 5:
                    raise UnreadableJpegError("frame header is truncated")
                height, width = struct.unpack(">HH", payload[1:5])
                if width == 0 or height == 0:
                    raise UnreadableJpegError("frame size is zero")
                found.size = (width, height)
        elif marker == 0xE1:
            if payload.startswith(_EXIF_ID):
                exif_orientation, exif_gps = _read_exif(payload[len(_EXIF_ID) :])
                if found.orientation is None:
                    found.orientation = exif_orientation
                found.has_exif_gps = found.has_exif_gps or exif_gps
            elif payload.startswith(XMP_IDS):
                found.has_xmp_gps = found.has_xmp_gps or bool(XMP_GPS_PATTERN.search(payload))
                if payload.startswith(_XMP_EXTENSION_ID):
                    found.extended_xmp.append(payload[len(_XMP_EXTENSION_ID) :])
    raise UnreadableJpegError("too many header segments")


def _embedded_images_have_gps(data: bytes) -> bool:
    """Looks for location data in the other JPEGs inside the file.

    Phones put more pictures in one file: an EXIF thumbnail, and after the main image
    MPF images, gain maps, depth maps. Each JPEG start after the first is walked like
    the main image; one that can't be read is ignored, keeping what was read before the
    failure. More than ``MAX_EMBEDDED_IMAGES`` starts make the file unreadable, so a
    location can't hide behind decoys.
    """
    has_gps = False
    position = data.find(_JPEG_START, 1)
    for _ in range(MAX_EMBEDDED_IMAGES):
        if position < 0:
            return has_gps
        found = _Headers()
        try:
            _walk_headers(data, position, found)
        except UnreadableJpegError:
            pass
        has_gps = has_gps or found.has_gps
        position = data.find(_JPEG_START, position + len(_JPEG_START))
    if position >= 0:
        raise UnreadableJpegError("too many embedded images")
    return has_gps


def read_jpeg_info(data: bytes) -> JpegInfo:
    """Reads the size, orientation and location flags from a JPEG's headers.

    The location flags cover the main image's headers, every embedded JPEG's headers,
    and XMP GPS properties anywhere after the main image's headers (a trailer).

    Raises ``NotJpegError`` when the bytes aren't a JPEG and ``UnreadableJpegError``
    when the headers are cut short or malformed. Nothing else.
    """
    if data[:3] != _JPEG_START:
        raise NotJpegError("missing the JPEG start marker")

    main = _Headers()
    _walk_headers(data, 0, main)
    if main.size is None:
        raise UnreadableJpegError("no frame header before the image data")
    trailer_xmp_gps = XMP_GPS_PATTERN.search(data, main.end) is not None
    return JpegInfo(
        width=main.size[0],
        height=main.size[1],
        orientation=main.orientation or 1,
        has_exif_gps=main.has_exif_gps,
        has_xmp_gps=main.has_xmp_gps or _extended_xmp_has_gps(main.extended_xmp) or trailer_xmp_gps,
        has_embedded_gps=_embedded_images_have_gps(data),
    )


def ratio_text(width: int, height: int) -> str:
    """The ratio as people read it: "4:3" when both reduced terms are small, else "1.33:1"."""
    divisor = math.gcd(width, height)
    if divisor and width // divisor <= RATIO_TERM_LIMIT and height // divisor <= RATIO_TERM_LIMIT:
        return f"{width // divisor}:{height // divisor}"
    return f"{width / height:.2f}:1"


def too_big_message(byte_count: int) -> str:
    """The size message, with the size in MB rounded up to one decimal."""
    tenths = -(-byte_count * 10 // _MEBIBYTE)
    return TOO_BIG_MESSAGE.format(size=tenths / 10)


def is_target_ratio(width: int, height: int) -> bool:
    """True when width:height is 3:2 within the relative tolerance."""
    target_width, target_height = TARGET_RATIO
    deviation = abs(width * target_height - height * target_width)
    return 100 * deviation <= RATIO_TOLERANCE_PERCENT * height * target_width


def check_photo(data: bytes) -> str | None:
    """The first problem's message, or None when the photo is acceptable."""
    if len(data) > MAX_PHOTO_BYTES:
        return too_big_message(len(data))
    try:
        info = read_jpeg_info(data)
    except NotJpegError:
        return NOT_JPEG_MESSAGE
    except UnreadableJpegError:
        return UNREADABLE_JPEG_MESSAGE

    width, height = info.displayed_size
    ratio = ratio_text(width, height)
    if width <= height:
        return NOT_LANDSCAPE_MESSAGE.format(width=width, height=height, ratio=ratio, example=EXAMPLE_SIZE)
    if not is_target_ratio(width, height):
        return WRONG_RATIO_MESSAGE.format(width=width, height=height, ratio=ratio, example=EXAMPLE_SIZE)
    if info.has_location:
        return LOCATION_MESSAGE
    return None
