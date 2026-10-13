"""Normalize user-selected reference images in memory; never retain originals."""
from __future__ import annotations

import base64
import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGES = 3
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 32 * 1024 * 1024
MAX_IMAGE_BYTES = 400 * 1024
MAX_SIDE = 1280
SUPPORTED = {"PNG", "JPEG", "WEBP", "GIF"}


class ImageError(ValueError):
    pass


def normalize(raw, name="参考图"):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_SOURCE_BYTES:
        raise ImageError("每张参考图需小于 20 MB。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in SUPPORTED:
                    raise ImageError("参考图支持 PNG、JPEG、WebP 和 GIF。")
                if source.width * source.height > MAX_PIXELS:
                    raise ImageError("参考图分辨率过大，请先缩小图片。")
                source.seek(0)
                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
                flattened = Image.new("RGB", image.size, "white")
                flattened.paste(image, mask=image.getchannel("A"))
        for side in (1280, 960, 640):
            if max(flattened.size) > side:
                flattened.thumbnail((side, side), Image.Resampling.LANCZOS)
            for quality in (88, 76, 62, 48):
                output = io.BytesIO()
                # No original EXIF, GPS or embedded filename travels to the model.
                flattened.save(output, "JPEG", quality=quality, optimize=True)
                content = output.getvalue()
                if len(content) <= MAX_IMAGE_BYTES:
                    safe_name = Path(str(name)).name[:200]
                    safe_name = "".join(c for c in safe_name if ord(c) >= 32) or "参考图"
                    return {"name": safe_name, "dataUrl": "data:image/jpeg;base64," + base64.b64encode(content).decode("ascii"),
                            "width": flattened.width, "height": flattened.height}
        raise ImageError("参考图仍然过大，请换用较小图片。")
    except ImageError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning,
            OSError, ValueError, SyntaxError, OverflowError):
        raise ImageError("参考图损坏或格式不受支持，请换一张图片。") from None


def from_paths(paths):
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_IMAGES:
        raise ImageError("每次请选择 1–3 张参考图。")
    result = []
    for value in paths:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ImageError("请通过参考图选择窗口添加图片。")
        try:
            path = Path(value)
            if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
                raise ImageError("参考图不存在或超过 20 MB。")
            with path.open("rb") as stream:
                raw = stream.read(MAX_SOURCE_BYTES + 1)
        except OSError:
            raise ImageError("无法读取参考图，请重新选择。") from None
        result.append(normalize(raw, path.name))
    return {"images": result}


def from_payload(images):
    if images is None:
        return []
    if not isinstance(images, list) or len(images) > MAX_IMAGES:
        raise ImageError("最多使用 3 张参考图。")
    result = []
    for item in images:
        if not isinstance(item, dict):
            raise ImageError("参考图数据无效，请重新添加。")
        url = item.get("dataUrl")
        prefix = "data:image/jpeg;base64,"
        if not isinstance(url, str) or not url.startswith(prefix) or len(url) > 560000:
            raise ImageError("参考图需使用 App 压缩后的 JPEG，请重新添加。")
        try:
            raw = base64.b64decode(url[len(prefix):], validate=True)
        except (ValueError, TypeError):
            raise ImageError("参考图编码无效，请重新添加。") from None
        if len(raw) > MAX_IMAGE_BYTES:
            raise ImageError("参考图过大，请重新添加。")
        # Re-normalize any untrusted frontend input and strip metadata again.
        result.append(normalize(raw, item.get("name", "参考图")))
    return result
