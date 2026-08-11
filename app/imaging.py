"""Image intake: validate, normalise orientation, downscale, and strip metadata.

EXIF is read for the user's benefit (so we can tell them their photo carried GPS
coordinates) and then dropped — the model only ever sees pixels, so the location
it reports is a genuine visual inference rather than a metadata lookup.
"""

from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass

from PIL import Image, ImageOps
from PIL.ExifTags import GPSTAGS, TAGS

ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"}


class ImageError(ValueError):
    """The upload is not an image we can work with."""


@dataclass(frozen=True)
class PreparedImage:
    # The re-encoded bytes, kept alongside their base64 form: providers send
    # the base64, and the history store writes the bytes. Both are of the
    # *normalised* image — downscaled, re-encoded, metadata already gone — so
    # nothing that touches either can put the original's EXIF anywhere.
    data: bytes
    data_b64: str
    media_type: str
    width: int
    height: int
    source_width: int
    source_height: int
    exif_gps: dict | None


def _rational(value) -> float | None:
    """One EXIF rational as a finite float, or None if it is not usable.

    A zero-denominator rational is legal in an EXIF file and Pillow hands it back
    as `nan` rather than raising. Returning 0.0 for it, as this used to, quietly
    turned a broken tag into a plausible coordinate; letting the `nan` through is
    worse still, because it then rides `meta.exifGps` all the way into a JSON
    response body, where `NaN` is not a token any JSON parser accepts.
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None
    return number if math.isfinite(number) else None


def _dms_to_degrees(dms, ref: str) -> float | None:
    try:
        parts = [_rational(part) for part in dms]
    except (TypeError, ValueError):
        return None
    if len(parts) != 3 or any(part is None for part in parts):
        return None  # a partly unreadable tag is not a location
    degrees, minutes, seconds = parts
    decimal = degrees + minutes / 60 + seconds / 3600
    if ref in {"S", "W"}:
        decimal = -decimal
    # The EXIF said something, but not something on Earth.
    if not math.isfinite(decimal) or abs(decimal) > 180:
        return None
    return round(decimal, 6)


def _read_exif_gps(image: Image.Image) -> dict | None:
    try:
        exif = image.getexif()
    except Exception:
        return None
    if not exif:
        return None

    gps_ifd = None
    for tag_id, value in exif.items():
        if TAGS.get(tag_id) == "GPSInfo":
            gps_ifd = exif.get_ifd(tag_id) if hasattr(exif, "get_ifd") else value
            break
    if not gps_ifd:
        return None

    tags = {GPSTAGS.get(key, key): value for key, value in dict(gps_ifd).items()}
    lat = tags.get("GPSLatitude")
    lon = tags.get("GPSLongitude")
    if not lat or not lon:
        return None

    latitude = _dms_to_degrees(lat, str(tags.get("GPSLatitudeRef", "N")))
    longitude = _dms_to_degrees(lon, str(tags.get("GPSLongitudeRef", "E")))
    if latitude is None or longitude is None:
        return None
    return {"lat": latitude, "lon": longitude}


def prepare(raw: bytes, max_edge: int) -> PreparedImage:
    """Decode an upload and return a model-ready JPEG payload."""
    try:
        probe = Image.open(io.BytesIO(raw))
        probe.load()
    except Exception as exc:  # Pillow raises a wide range of decode errors
        raise ImageError("这个文件不是可识别的图片格式。") from exc

    if probe.format not in ACCEPTED_FORMATS:
        raise ImageError(f"暂不支持 {probe.format or '该'} 格式，请上传 JPG、PNG 或 WebP。")

    exif_gps = _read_exif_gps(probe)
    source_width, source_height = probe.size

    image = ImageOps.exif_transpose(probe)
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")

    longest = max(image.size)
    if longest > max_edge:
        scale = max_edge / longest
        target = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(target, Image.LANCZOS)

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=88, optimize=True)
    encoded = buffer.getvalue()

    return PreparedImage(
        data=encoded,
        data_b64=base64.b64encode(encoded).decode("ascii"),
        media_type="image/jpeg",
        width=image.width,
        height=image.height,
        source_width=source_width,
        source_height=source_height,
        exif_gps=exif_gps,
    )
