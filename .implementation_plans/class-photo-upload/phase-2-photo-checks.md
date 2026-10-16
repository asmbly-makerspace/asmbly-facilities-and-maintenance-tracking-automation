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

> **Status:** [ ] Pending

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
TARGET_RATIO = 3 / 2
RATIO_TOLERANCE = 0.01          # relative: abs(r - 1.5) / 1.5 <= 0.01
EXAMPLE_SIZE = "1500×1000"
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
    has_exif_gps: bool    # IFD0 has tag 0x8825
    has_xmp_gps: bool     # an XMP APP1 segment matches XMP_GPS_PATTERN

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
   ends the walk. Otherwise read a big-endian 2-byte length (at least 2) and the payload;
   any read past the end → `UnreadableJpegError`.
3. A SOF marker: height = payload[1:3], width = payload[3:5] (big-endian). Zero width or
   height → `UnreadableJpegError`. Keep the first SOF.
4. `0xE1` (APP1): payload starting `b"Exif\x00\x00"` → parse TIFF from payload[6:]: byte
   order `II` or `MM` (else unreadable), magic 42, IFD0 offset; read the entry count and
   each 12-byte entry with bounds checks. Tag `0x0112` → orientation (SHORT value); tag
   `0x8825` present → `has_exif_gps = True` (presence alone counts: the page removes the
   tag). Payload starting with one of `XMP_IDS` → `has_xmp_gps |= bool(XMP_GPS_PATTERN.search(payload))`.
5. No SOF before the walk ends → `UnreadableJpegError`.

`check_photo` order: size (`len(data) > MAX_PHOTO_BYTES`), then `read_jpeg_info`
(mapping the two errors to their messages), then the ratio on `displayed_size`
(portrait or square when `w <= h`), then location (`has_exif_gps or has_xmp_gps`).
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
    xmp_plain: bool = False,
    byte_order: str = "II",
    sof_marker: int = 0xC0,
    pad_to: int | None = None,
) -> bytes:
```

SOI, an APP1 EXIF segment when `orientation` or `exif_gps` is set (IFD0 with tag
`0x0112` and/or tag `0x8825` pointing to a GPS IFD with one `GPSLatitudeRef` entry), an
APP1 XMP segment when `xmp_gps` (contains `exif:GPSLatitude="30,16.5N"`) or `xmp_plain`
(contains only `dc:title`), a SOF segment with the size, a minimal SOS segment, some
filler entropy bytes (padded with a COM segment before SOS to `pad_to` bytes when set),
and EOI. The output is not a decodable picture; it only has to parse.

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
  seed, 200 cases of 0–64 bytes): returns a string, never raises.

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
  `read_jpeg_info(data) -> JpegInfo`, `MAX_PHOTO_BYTES`, the message texts.
- `functions/classes/class_photo_upload_api/tests/jpeg_builder.make_jpeg(...)` for later
  tests.
