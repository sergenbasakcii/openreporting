"""Customer logos for reports.

Uploads are decoded with Pillow, checked (type, pixel count), downscaled and re-encoded as a
plain PNG. Only that re-encoded file is stored and embedded, so metadata, scripts or malformed
chunks in the original never reach a PDF. Files are content-addressed: ``logos/<sha256>.png``.
"""

import base64
import binascii
import hashlib
import io
import re

from PIL import Image, UnidentifiedImageError

from ..domain import DomainError

MAX_UPLOAD_BYTES = 1_000_000
MAX_SOURCE_PIXELS = 25_000_000
MAX_EDGE = 1200
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
_ID = re.compile(r"^[0-9a-f]{64}$")


class LogoError(DomainError):
    pass


def _directory(settings):
    path = settings.data_dir / "logos"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def decode_upload(data):
    """Accept raw base64 or a ``data:image/...;base64,`` URL from the browser."""
    if not isinstance(data, str) or not data:
        raise LogoError("Logo verisi boş")
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    if len(data) > MAX_UPLOAD_BYTES * 4 // 3 + 8:
        raise LogoError("Logo en fazla 1 MB olabilir")
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise LogoError("Logo verisi okunamadı") from exc


def normalize(raw):
    """Validated, downscaled PNG bytes for an uploaded image."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise LogoError("Logo en fazla 1 MB olabilir")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise LogoError("Logo PNG, JPG, WebP veya GIF olmalı")
            if probe.width * probe.height > MAX_SOURCE_PIXELS:
                raise LogoError("Logo çözünürlüğü çok yüksek")
            probe.seek(0)
            image = probe.convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise LogoError("Dosya geçerli bir resim değil") from exc
    image.thumbnail((MAX_EDGE, MAX_EDGE))
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        raise LogoError("Logo tamamen saydam")
    image = image.crop(bbox)  # trim transparent padding so the logo fills its box
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def save(settings, data):
    png = normalize(decode_upload(data))
    logo_id = hashlib.sha256(png).hexdigest()
    target = _directory(settings) / f"{logo_id}.png"
    if not target.exists():
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(png)
        tmp.replace(target)
    with Image.open(target) as img:
        width, height = img.size
    return {"id": logo_id, "width": width, "height": height}


def path(settings, logo_id):
    if not isinstance(logo_id, str) or not _ID.fullmatch(logo_id):
        raise LogoError("Logo kimliği geçersiz")
    target = settings.data_dir / "logos" / f"{logo_id}.png"
    if not target.is_file():
        raise LogoError("Logo bulunamadı; yeniden yükleyin")
    return target
