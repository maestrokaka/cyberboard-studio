"""Opt-in wardrobe generation; only the bundled character and outfit brief leave the device."""
from __future__ import annotations

import base64
import binascii
import io
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError
from speech_input import SpeechError, SpeechSettings, atomic

ENDPOINTS = {"china": "https://api.minimax.cn/v1/image_generation",
             "global": "https://api.minimax.io/v1/image_generation"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REPLY_BYTES = 24 * 1024 * 1024


class CompanionError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise CompanionError(message)


class Wardrobe:
    def __init__(self, state_dir, resource_dir, opener=None):
        self.root = Path(state_dir)
        self.assets = Path(resource_dir) / "web/assets/companion"
        self.config = self.root / "companion-image-settings.json"
        self.key_file = self.root / "companion-image.key"
        self.folder = self.root / "companion-outfits"
        self.opener = opener or urllib.request.build_opener()

    def settings(self, payload=None):
        value = {"region": "china"}
        if self.config.exists():
            require(self.config.stat().st_size <= 4096, "换装连接设置过大，请重新保存。")
            value = json.loads(self.config.read_text())
        require(value.get("region") in ENDPOINTS, "请选择正确的 MiniMax 接口区域。")
        try: reuse = bool(SpeechSettings(self.root).key("minimax-asr"))
        except SpeechError: reuse = False
        return {"provider": "minimax-image", "model": "image-01", "region": value["region"],
                "hasKey": self.key_file.is_file() and bool(self.key_file.stat().st_size),
                "canReuseVoiceKey": reuse}

    def save(self, payload):
        region = payload.get("region", "china")
        require(region in ENDPOINTS, "请选择正确的接口区域。")
        key = payload.get("apiKey", "")
        require(isinstance(key, str), "Key 格式无效。")
        if payload.get("reuseVoiceKey") is True:
            key = SpeechSettings(self.root).key("minimax-asr") or ""
            require(key, "请先保存 MiniMax 语音 Key，或直接填写生图 Key。")
        if key:
            require(len(key) <= 4096 and all(33 <= ord(c) <= 126 for c in key), "Key 格式无效。")
            atomic(self.key_file, key.encode())
        if payload.get("removeKey") is True:
            self.key_file.unlink(missing_ok=True)
        atomic(self.config, json.dumps({"region": region}).encode())
        return self.settings()

    def reveal(self, payload=None):
        require(not self.key_file.exists() or self.key_file.stat().st_size <= 4096, "Key 无法读取，请重新保存。")
        return {"apiKey": self.key_file.read_text() if self.key_file.exists() else ""}

    @staticmethod
    def normalize(raw):
        require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_IMAGE_BYTES, "生成图片过大或为空。")
        try:
            with Image.open(io.BytesIO(raw)) as source:
                require(source.format in {"PNG", "JPEG", "WEBP"}, "生成服务没有返回可用图片。")
                require(128 <= source.width <= 4096 and 128 <= source.height <= 4096,
                        "生成图片尺寸无效。")
                require(source.width * source.height <= 8_500_000, "生成图片像素过多。")
                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.thumbnail((768, 1536))
                # Image-01 does not promise alpha. A requested chroma background
                # is removed only where pixels are clearly green, never by AI.
                pixels = image.load()
                for y in range(image.height):
                    for x in range(image.width):
                        r, g, b, a = pixels[x, y]
                        if g > 90 and g > r * 1.55 and g > b * 1.55:
                            pixels[x, y] = (0, 0, 0, 0)
                alpha = image.getchannel("A")
                require(alpha.getbbox() is not None, "生成图片没有可见角色，请重试。")
                require(alpha.histogram()[0] > image.width * image.height * .08,
                        "图片背景未能去除，请使用纯绿色背景重新生成。")
                image = image.crop(alpha.getbbox())
                image.thumbnail((736, 1472))
                canvas = Image.new("RGBA", (768, 1536))
                canvas.alpha_composite(image, ((768 - image.width) // 2, 1536 - image.height - 32))
                image = canvas
                output = io.BytesIO(); image.save(output, "PNG", optimize=True)
                return output.getvalue()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise CompanionError("生成图片无法读取，请重试。") from None

    def generate(self, payload):
        settings = self.settings()
        require(settings["hasKey"], "请先保存支持 image-01 的 MiniMax 生图 Key。")
        brief = payload.get("prompt", "")
        require(isinstance(brief, str) and 1 <= len(brief.strip()) <= 600, "请填写 1–600 字的服装描述。")
        hair = payload.get("hair", "short")
        require(hair in {"short", "long"}, "发型选项无效。")
        outfit = "sailor-long" if hair == "long" else "sailor-short"
        reference = (self.assets / outfit / "idle.png").read_bytes()
        require(len(list(self.folder.glob("custom-*.png"))) < 20, "最多保留 20 套 AI 衣装，请先删除不用的衣装。")
        request_payload = {
            "model": "image-01", "n": 1, "aspect_ratio": "9:16", "response_format": "base64",
            "prompt_optimizer": False,
            "subject_reference": [{"type": "character", "image_file": "data:image/png;base64," + base64.b64encode(reference).decode()}],
            "prompt": ("Single full-body adult 23-year-old orange-and-white catgirl desktop assistant. "
                       "Preserve the reference face, amber eyes, orange-white hair, ears, fluffy tail and elegant adult proportions. "
                       + ("Waist-length flowing hair. " if hair == "long" else "Short bob hairstyle. ")
                       + "Change only the fully clothed outfit: " + brief.strip()
                       + ". Neutral front standing pose, hands down, full ears and shoes visible, no props or text. "
                       "Premium anime illustration. Solid pure chroma green #00FF00 background, no green in clothing. "
                       "Clothes cover torso and hips completely, no nudity, no revealing or sexual pose.")}
        require(self.key_file.stat().st_size <= 4096, "Key 无法读取，请重新保存。")
        key = self.key_file.read_text().strip()
        require(bool(key) and all(33 <= ord(c) <= 126 for c in key), "Key 格式无效。")
        request = urllib.request.Request(ENDPOINTS[settings["region"]], data=json.dumps(request_payload).encode(),
                                         headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=120) as response:
                raw = response.read(MAX_REPLY_BYTES + 1)
            require(len(raw) <= MAX_REPLY_BYTES, "生图服务回复过大，已停止。")
            reply = json.loads(raw)
            code = (reply.get("base_resp") or {}).get("status_code", 0)
            require(code == 0, "生图服务拒绝请求，请检查余额和 image-01 权限；Coding Key 不一定支持生图。")
            data = reply.get("data") or {}
            images = data.get("image_base64") or data.get("image_base64s") or []
            if isinstance(images, str): images = [images]
            require(isinstance(images, list) and len(images) == 1 and isinstance(images[0], str), "生图服务没有返回完整图片。")
            encoded = images[0].split(",", 1)[-1]
            require(len(encoded) <= MAX_IMAGE_BYTES * 4 // 3 + 8, "生成图片过大。")
            png = self.normalize(base64.b64decode(encoded, validate=True))
        except urllib.error.HTTPError as error:
            error.close()
            raise CompanionError("生图请求未完成，请检查 Key、图片权限与账户额度。") from None
        except (urllib.error.URLError, TimeoutError):
            raise CompanionError("生图服务连接失败或超过 120 秒，请检查网络后重试；没有自动重发。") from None
        except (ValueError, binascii.Error, AttributeError, TypeError) as error:
            if isinstance(error, CompanionError): raise
            raise CompanionError("生图服务回复无法读取，请重试。") from None
        identity = "custom-" + uuid.uuid4().hex
        atomic(self.folder / (identity + ".png"), png)
        atomic(self.folder / (identity + ".json"), json.dumps({"hair": hair}, ensure_ascii=False).encode())
        return {"id": identity, "name": "AI 衣装", "hair": hair, "builtin": False,
                "imageDataUrl": "data:image/png;base64," + base64.b64encode(png).decode(),
                "staticPose": True, "applied": False}

    def delete(self, payload):
        identity = payload.get("id", "")
        require(isinstance(identity, str) and re.fullmatch(r"custom-[0-9a-f]{32}", identity), "只能删除本机 AI 衣装。")
        (self.folder / (identity + ".png")).unlink(missing_ok=True)
        (self.folder / (identity + ".json")).unlink(missing_ok=True)
        return {"deleted": True, "id": identity}
