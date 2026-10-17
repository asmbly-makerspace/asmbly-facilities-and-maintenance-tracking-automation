"""Builds small synthetic JPEG byte strings for tests.

The output parses like a JPEG (markers, EXIF, XMP, frame and scan headers) but is not a
decodable picture: the "image data" is filler.
"""

import struct

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
XMP_ID = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_EXTENSION_ID = b"http://ns.adobe.com/xmp/extension/\x00"
EXTENDED_XMP_GUID = b"0123456789ABCDEF0123456789ABCDEF"
FILLER = b"\x12\x34\x56\x78" * 8

_XMP_GPS_PACKET = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/" '
    b'exif:GPSLatitude="30,16.5N"/></rdf:RDF></x:xmpmeta>'
)
_XMP_PLAIN_PACKET = (
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    b'<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
    b"<dc:title>Woodshop</dc:title></rdf:Description></rdf:RDF></x:xmpmeta>"
)


def segment(marker: int, payload: bytes) -> bytes:
    """A marker segment: FF, the marker, a big-endian length (payload + 2), the payload."""
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def _ifd(order: str, entries: list[tuple[int, int, int, bytes]], next_offset: int = 0) -> bytes:
    out = struct.pack(order + "H", len(entries))
    for tag, value_type, count, value in entries:
        out += struct.pack(order + "HHI", tag, value_type, count) + value
    return out + struct.pack(order + "I", next_offset)


def _ifd_length(entry_count: int) -> int:
    return 2 + 12 * entry_count + 4


def _exif_payload(
    orientation: int | None,
    exif_gps: bool,
    exif_gps_ifd: str,
    byte_order: str,
    ifd0_offset: int | None,
) -> bytes:
    """EXIF APP1 payload. ``exif_gps_ifd`` puts the GPS IFD pointer in "ifd0" (where it
    belongs), "ifd1" (the thumbnail IFD) or "exif" (the Exif sub-IFD)."""
    order = ">" if byte_order == "MM" else "<"
    gps_in = exif_gps_ifd if exif_gps else None
    ifd0_entry_count = (orientation is not None) + (gps_in in ("ifd0", "exif"))
    second_ifd_offset = 8 + _ifd_length(ifd0_entry_count)
    second_ifd = gps_in in ("ifd1", "exif")
    gps_ifd_offset = second_ifd_offset + (_ifd_length(1) if second_ifd else 0)
    gps_pointer = (0x8825, 4, 1, struct.pack(order + "I", gps_ifd_offset))

    ifd0_entries: list[tuple[int, int, int, bytes]] = []
    if orientation is not None:
        ifd0_entries.append((0x0112, 3, 1, struct.pack(order + "H", orientation) + b"\x00\x00"))
    if gps_in == "ifd0":
        ifd0_entries.append(gps_pointer)
    if gps_in == "exif":
        ifd0_entries.append((0x8769, 4, 1, struct.pack(order + "I", second_ifd_offset)))

    first_ifd = ifd0_offset if ifd0_offset is not None else 8
    tiff = byte_order.encode("ascii") + struct.pack(order + "HI", 42, first_ifd)
    tiff += _ifd(order, ifd0_entries, second_ifd_offset if gps_in == "ifd1" else 0)
    if second_ifd:
        tiff += _ifd(order, [gps_pointer])
    if gps_in:
        # GPS IFD with one GPSLatitudeRef ("N").
        tiff += _ifd(order, [(0x0001, 2, 2, b"N\x00\x00\x00")])
    return b"Exif\x00\x00" + tiff


def extended_xmp_segments(chunks: list[bytes]) -> bytes:
    """Extended XMP APP1 segments carrying ``chunks`` in order, under one GUID."""
    total = sum(len(chunk) for chunk in chunks)
    out = b""
    offset = 0
    for chunk in chunks:
        header = EXTENDED_XMP_GUID + struct.pack(">II", total, offset)
        out += segment(0xE1, XMP_EXTENSION_ID + header + chunk)
        offset += len(chunk)
    return out


def make_jpeg(
    width: int,
    height: int,
    *,
    orientation: int | None = None,
    exif_gps: bool = False,
    exif_gps_ifd: str = "ifd0",
    xmp_gps: bool = False,
    xmp_plain: bool = False,
    xmp_extended_chunks: list[bytes] | None = None,
    byte_order: str = "II",
    ifd0_offset: int | None = None,
    sof_marker: int | None = 0xC0,
    pad_to: int | None = None,
    trailer: bytes = b"",
) -> bytes:
    """A JPEG-shaped byte string with the given headers.

    ``sof_marker=None`` leaves out the frame header. ``pad_to`` pads the filler image
    data so the whole output (before ``trailer``) is exactly that many bytes. ``trailer``
    goes after EOI, where phones put MPF images, gain maps and motion-photo video.
    """
    out = SOI + segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    if orientation is not None or exif_gps:
        out += segment(0xE1, _exif_payload(orientation, exif_gps, exif_gps_ifd, byte_order, ifd0_offset))
    if xmp_gps:
        out += segment(0xE1, XMP_ID + _XMP_GPS_PACKET)
    if xmp_plain:
        out += segment(0xE1, XMP_ID + _XMP_PLAIN_PACKET)
    if xmp_extended_chunks:
        out += extended_xmp_segments(xmp_extended_chunks)
    if sof_marker is not None:
        components = b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
        out += segment(sof_marker, struct.pack(">BHHB", 8, height, width, 3) + components)
    out += segment(0xDA, b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00")

    filler = FILLER
    if pad_to is not None:
        missing = pad_to - len(out) - len(EOI)
        if missing < 0:
            raise ValueError(f"pad_to={pad_to} is smaller than the JPEG itself")
        filler = (FILLER * (missing // len(FILLER) + 1))[:missing]
    return out + filler + EOI + trailer
