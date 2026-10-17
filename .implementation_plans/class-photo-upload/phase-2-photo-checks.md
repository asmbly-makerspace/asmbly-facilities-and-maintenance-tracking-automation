---
phase_id: 2
title: Photo checks
epic: 73
implements: [105, 106]
depends_on: [1]
domain: [lambda]
estimated_size: M
---

# Phase 2: Photo checks

> **Status:** [x] Complete — 2026-10-16 on branch claude/inspiring-bell-o4i5t9

## Required reading

- `CLAUDE.md`, and #73's "Checks" section.
- Phase 1's hand-off (the `functions/classes/class_photo_upload_api/` package exists).
- `functions/networking/dynamic_dns_update/lambda_function.py` for style.
- The JPEG marker layout (ITU T.81, B.1.1) and the EXIF/TIFF layout (EXIF 2.3:
  TIFF header, IFD0, tag `0x0112` Orientation, tag `0x8825` GPS IFD pointer), and XMP's
  APP1 identifiers `http://ns.adobe.com/xap/1.0/\0` and
  `http://ns.adobe.com/xmp/extension/\0`. No image library: the server reads headers only.

## Goal

The server can decide, from a photo's bytes alone, whether it is acceptable, and say
what to fix in the words #73 asks for. Checked: size, JPEG by content, 3:2 landscape
within 1% after the orientation flag, and no location data. The same messages are used
by the page in phase 6 (it copies the strings), so a person sees the same text whether
the browser or the server catches the problem.

## Files to create

- `functions/classes/class_photo_upload_api/photo_checks.py`.
- `functions/classes/class_photo_upload_api/tests/jpeg_builder.py`: builds small,
  synthetic JPEG byte strings for tests (also used by phases 4 and 5).
- `functions/classes/class_photo_upload_api/tests/test_photo_checks.py`.

## Files to modify

None.

## Implementation details

### lambda: `photo_checks.py`

Constants:

```python
MAX_PHOTO_BYTES = 4 * 1024 * 1024
TARGET_RATIO = (3, 2)           # width:height
RATIO_TOLERANCE_PERCENT = 1     # relative: abs(r - 1.5) / 1.5 <= 0.01, compared in integers
EXAMPLE_SIZE = "1500×1000"
MAX_HEADER_SEGMENTS = 1000      # per image walk; more → unreadable
MAX_EMBEDDED_IMAGES = 16        # JPEG starts after the first; more → unreadable
SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
XMP_IDS = (b"http://ns.adobe.com/xap/1.0/\x00", b"http://ns.adobe.com/xmp/extension/\x00")
XMP_GPS_PATTERN = re.compile(rb"GPS(Latitude|Longitude|Altitude|DestLatitude|DestLongitude)")
```

Messages (module constants or functions; phase 6 copies them into the page):

| Problem | Message |
| --- | --- |
| Too big | `This photo is {size:.1f} MB. Class photos must be 4 MB or less. Export it at a smaller size and try again.` (`size` = bytes / 1024 / 1024 rounded **up** to one decimal, so a file just over the limit reads 4.1 MB, never 4.0 MB) |
| Not a JPEG | `This file isn't a JPEG photo. Save or export it as a JPEG (.jpg) and try again.` |
| Unreadable JPEG | `This JPEG couldn't be read. Export it again as a JPEG and try again.` |
| Wrong ratio, landscape | `This photo is {w}×{h}, which is {ratio}. Class photos must be 3:2, for example 1500×1000. Crop it and try again.` |
| Portrait or square | `This photo is {w}×{h}, which is {ratio} and not landscape. Class photos must be 3:2 landscape, for example 1500×1000. Crop it and try again.` |
| Location data | `This photo still has location data. Use the upload page, which removes it.` |

`{w}×{h}` is the size as displayed (after the orientation flag). `{ratio}`: with
`g = gcd(w, h)`, `"{w//g}:{h//g}"` when both terms are at most 32, else
`"{w/h:.2f}:1"`. So 4000×3000 reads "4:3" and 1999×1000 reads "2.00:1".

```python
class NotJpegError(ValueError): ...
class UnreadableJpegError(ValueError): ...

@dataclass(frozen=True)
class JpegInfo:
    width: int            # as stored in the SOF segment
    height: int
    orientation: int      # 1..8; 1 when absent or out of range
    has_exif_gps: bool    # tag 0x8825 in IFD0, IFD1 or the Exif sub-IFD
    has_xmp_gps: bool     # an XMP APP1 segment, or the bytes after the main headers,
                          # match XMP_GPS_PATTERN
    has_embedded_gps: bool  # another JPEG inside the file has EXIF or XMP GPS

    @property
    def has_location(self) -> bool: ...

    @property
    def displayed_size(self) -> tuple[int, int]:
        """Width and height after the orientation flag (5-8 swap them)."""

def read_jpeg_info(data: bytes) -> JpegInfo: ...
def ratio_text(width: int, height: int) -> str: ...
def check_photo(data: bytes) -> str | None:
    """The first problem's message, or None when the photo is acceptable."""
```

`read_jpeg_info`:

1. `data[:3] != b"\xff\xd8\xff"` → `NotJpegError`.
2. Walk the segments from offset 2: expect `0xFF`, skip extra `0xFF` fill bytes, read
   the marker. `0x01` and `0xD0`–`0xD7` have no length. `0xD9` (EOI) or `0xDA` (SOS)
   ends the walk; more than `MAX_HEADER_SEGMENTS` segments → `UnreadableJpegError`. Otherwise read a big-endian 2-byte length (at least 2) and the payload;
   any read past the end → `UnreadableJpegError`.
3. A SOF marker: height = payload[1:3], width = payload[3:5] (big-endian). Zero width or
   height → `UnreadableJpegError`. Keep the first SOF.
4. `0xE1` (APP1): payload starting `b"Exif\x00\x00"` → parse TIFF from payload[6:]: byte
   order `II` or `MM` (else unreadable), magic 42, IFD0 offset; read the entry count and
   each 12-byte entry with bounds checks. Tag `0x0112` → orientation (type SHORT, count 1:
   the value is the first 2 bytes of the 4-byte value field, in the file's byte order; any
   other type or count counts as absent, so orientation 1); tag
   `0x8825` present → `has_exif_gps = True` (presence alone counts: the page removes the
   tag). The pointer is also looked for in IFD1 (IFD0's next-IFD offset) and the Exif
   sub-IFD (tag `0x8769`), each read once with no further pointers followed; one out of
   range is ignored, and one cut short is read as far as its whole entries go. Payload starting with one of `XMP_IDS` → `has_xmp_gps |= bool(XMP_GPS_PATTERN.search(payload))`.
   Extended XMP chunks (after the ID: 32-byte GUID, 4-byte full length, 4-byte offset,
   then data) are also joined in segment order and searched once more after the walk, so
   a property name split across two chunks is still found.
5. No SOF before the walk ends → `UnreadableJpegError`.
6. Embedded images: every further `FF D8 FF` in the file (EXIF thumbnails, and MPF
   images, gain maps and depth maps after the main EOI) is walked the same way. One that
   can't be read is ignored, keeping the flags read before the failure; more than
   `MAX_EMBEDDED_IMAGES` → `UnreadableJpegError`. Any GPS found → `has_embedded_gps`.
7. Trailer: the bytes after the main image's SOS are searched for `XMP_GPS_PATTERN`
   (an XMP packet appended outside any JPEG) → `has_xmp_gps`.

`check_photo` order: size (`len(data) > MAX_PHOTO_BYTES`), then `read_jpeg_info`
(mapping the two errors to their messages), then the ratio on `displayed_size`
(portrait or square when `w <= h`; otherwise refused when
`100 * abs(2 * w - 3 * h) > 3 * h`, the 1% rule in integers so the 1515×1000 boundary
does not depend on floating point; phase 6 copies the same formula), then location
(`has_location`).
Returns the first message. It logs nothing (the caller logs the outcome with IDs).

### tests: `jpeg_builder.py`

```python
def make_jpeg(
    width: int,
    height: int,
    *,
    orientation: int | None = None,
    exif_gps: bool = False,
    xmp_gps: bool = False,
    exif_gps_ifd: str = "ifd0",       # or "ifd1", "exif": where the GPS pointer goes
    xmp_gps: bool = False,
    xmp_plain: bool = False,
    xmp_extended_chunks: list[bytes] | None = None,
    byte_order: str = "II",
    ifd0_offset: int | None = None,
    sof_marker: int | None = 0xC0,    # None leaves the frame header out
    pad_to: int | None = None,
    trailer: bytes = b"",             # appended after EOI
) -> bytes:
```

SOI, an APP1 EXIF segment when `orientation` or `exif_gps` is set (IFD0 with tag
`0x0112` and/or tag `0x8825` pointing to a GPS IFD with one `GPSLatitudeRef` entry), an
APP1 XMP segment when `xmp_gps` (contains `exif:GPSLatitude="30,16.5N"`) or `xmp_plain`
(contains only `dc:title`), a SOF segment with the size, a minimal SOS segment, some
filler entropy bytes (lengthened to make the output `pad_to` bytes when set: a COM
segment can't fill a 1–3 byte gap), EOI, and `trailer`. The output is not a decodable picture; it only has to parse.

## Tests

`tests/test_photo_checks.py`:

- `test_accepts_exact_3_2` (1500×1000) and `test_accepts_within_tolerance` (2000×1334,
  4000×2667, 1515×1000) → `None`.
- `test_refuses_outside_tolerance` (1520×1000, 1480×1000): the ratio message.
- `test_refuses_4_3_with_example_message`: 4000×3000 gives exactly
  "This photo is 4000×3000, which is 4:3. Class photos must be 3:2, for example 1500×1000. Crop it and try again."
- `test_refuses_portrait` (1000×1500) and `test_refuses_square` (1000×1000): the
  "not landscape" message.
- `test_orientation_swaps_size` (parametrized over 1–8): stored 1500×1000 with flag 5,
  6, 7 or 8 is refused as 1000×1500 portrait; flags 1–4 are accepted. Stored 1000×1500
  with flag 6 is accepted.
- `test_orientation_big_endian`: the same with `byte_order="MM"`.
- `test_refuses_png_bytes`: `b"\x89PNG\r\n\x1a\n..."` → the not-JPEG message, regardless
  of a `.jpg` name (there is no name input at all).
- `test_refuses_truncated_jpeg`: a valid header cut inside the SOF → unreadable message;
  `test_refuses_jpeg_without_sof`; `test_refuses_bad_segment_length`;
  `test_refuses_bad_tiff_byte_order`; `test_refuses_ifd_offset_out_of_range`.
- `test_reads_progressive_sof` (`sof_marker=0xC2`).
- `test_refuses_over_4_mb`: `pad_to=4 * 1024 * 1024 + 1` → "This photo is 4.1 MB. Class photos must be 4 MB or
  less. …" (rounded up); exactly `4 * 1024 * 1024` bytes is accepted.
- `test_refuses_exif_gps` and `test_refuses_xmp_gps`: the location message.
- `test_accepts_plain_xmp`: XMP without GPS fields is fine.
- `test_size_is_checked_before_parsing`: an oversized PNG gets the size message (one
  message at a time, the cheapest first).
- `test_ratio_text` (parametrized): 4000×3000 → `4:3`, 1920×1080 → `16:9`, 1000×1000 →
  `1:1`, 1999×1000 → `2.00:1`.
- `test_check_photo_never_raises` (parametrized over random byte strings from a fixed
  seed, 200 cases of 0–64 bytes): returns a string, never raises. Random bytes almost
  never start with `FF D8 FF`, so a second parametrized set (fixed seed, 200 cases) takes
  a valid `make_jpeg(..., orientation=6, exif_gps=True, xmp_gps=True)` and truncates it
  at a random offset or overwrites a few random bytes: `check_photo` returns `None` or a
  string, never raises, and `read_jpeg_info` raises only the two errors.
- `test_refuses_xmp_gps_split_across_extended_chunks`: `GPSLatitude` split between two
  extended XMP segments → the location message.
- Added in phase 2's review: `test_refuses_gps_pointer_outside_ifd0` (IFD1, Exif
  sub-IFD), `test_ignores_ifd1_out_of_range`, `test_reads_partial_exif_sub_ifd`,
  `test_refuses_gps_in_image_after_eoi`, `test_refuses_location_in_embedded_image`,
  `test_refuses_xmp_gps_in_trailer_outside_any_image`, `test_accepts_clean_embedded_images`,
  `test_ignores_unreadable_embedded_image`, `test_embedded_image_limit`,
  `test_header_segment_limit`, `test_hostile_photo_is_checked_quickly`, and
  `test_real_photo_headers` on three real asmbly-classes images' headers (expected values
  from ImageMagick's `identify`).

## Acceptance criteria

1. A non-JPEG (by content), an unreadable JPEG, an oversized file, a non-3:2 or portrait
   photo (after orientation), and a photo with EXIF or XMP GPS each get their message
   from `check_photo`. (#105 AC1–AC4, #106 AC4)
2. 2000×1334 and 1500×1000 pass; 1000×1500 and 1500×1000 with orientation 5–8 fail.
   (#105 AC3)
3. The 4:3 message matches #73's example word for word. (#105 AC2)
4. `check_photo` never raises on arbitrary bytes.
5. `.venv/bin/python -m pytest` passes.

## Verification

```bash
.venv/bin/python -m pytest functions/classes
.venv/bin/python -m pytest
```

No template change. Nothing to see on stage yet.

## Admin actions

None.

## Hand-off

- `functions.classes.class_photo_upload_api.photo_checks`: `check_photo(data) -> str | None`,
  `read_jpeg_info(data) -> JpegInfo` (raises only `NotJpegError` / `UnreadableJpegError`),
  `MAX_PHOTO_BYTES`, `ratio_text`, `is_target_ratio(w, h)`, `too_big_message(n)`.
  Message constants for phase 6 to copy: `TOO_BIG_MESSAGE`, `NOT_JPEG_MESSAGE`,
  `UNREADABLE_JPEG_MESSAGE`, `WRONG_RATIO_MESSAGE`, `NOT_LANDSCAPE_MESSAGE` (format
  fields `width`, `height`, `ratio`, `example`; `example` is `EXAMPLE_SIZE`) and
  `LOCATION_MESSAGE`. The module logs nothing; the caller logs the outcome.
- `JpegInfo.has_location` is what `check_photo` refuses on; `has_embedded_gps` says the
  location is in an embedded image (useful in the caller's log line).
- `functions/classes/class_photo_upload_api/tests/jpeg_builder`: `make_jpeg(width, height,
  *, ...)` as above, plus `segment(marker, payload)` and `extended_xmp_segments(chunks)`.
  Real headers of three asmbly-classes images are in `tests/fixtures/asmbly_classes_*_headers.bin`. Import it as
  `functions.classes.class_photo_upload_api.tests.jpeg_builder`.
- When several EXIF APP1 segments exist, orientation comes from the first; GPS from any.
- For phase 6: the browser's ratio check uses the same integer formula; when GPS
  properties are found only in the joined extended XMP data, the browser drops every
  extended XMP chunk; and the browser must clean every place the server checks (IFD1,
  the Exif sub-IFD, embedded images, trailers). Phase 6's "Photo" step says how.
- For the manual QA doc: a malformed EXIF APP1 in the main image (bad byte order, bad
  magic, IFD0 out of range or cut short) refuses the whole file as unreadable ("This
  JPEG couldn't be read…"), even though browsers show such a photo; re-exporting fixes
  it. So does a file with more than 16 embedded JPEG starts.
- Location data means GPS coordinates; place names are not checked (README Decision 25).
  Nothing deferred.
