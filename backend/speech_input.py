"""Bounded, opt-in dictation. Audio exists in memory only; keys stay local.

This module does not execute agents, send a creative turn, or touch USB.
Only catalogued official ASR models are accepted; image capability is not ASR.
"""
from __future__ import annotations

import base64
import binascii
import errno
import io
import json
import os
from pathlib import Path
import re
import socket
import ssl
import tempfile
import urllib.error
import urllib.request
import uuid
import wave

MAX_AUDIO = 6 * 1024 * 1024
MAX_RESPONSE = 64 * 1024
MAX_SECONDS = 60.5
REQUEST_TIMEOUT_SECONDS = 60
CATALOG = {
    "qwen-asr": {"name": "千问语音识别", "models": ["qwen3-asr-flash"],
                 "regions": {"china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                             "global": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"}},
    "openai-asr": {"name": "OpenAI 语音识别", "models": ["gpt-transcribe", "gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1"],
                   "regions": {"global": "https://api.openai.com/v1"}},
    "minimax-asr": {"name": "MiniMax 语音识别", "models": ["asr-1.0"],
                    "regions": {"china": "https://api.minimax.cn/v1",
                                "global": "https://api.minimax.io/v1"}},
}


class SpeechError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def network_failure(error, item):
    """Map transport exceptions to safe, actionable diagnostics.

    Never include exception text: urllib/socket errors may contain URLs or
    gateway-provided data. The returned metadata is an allowlisted summary.
    """
    cause = error
    for _ in range(3):
        if isinstance(cause, urllib.error.URLError) and isinstance(cause.reason, BaseException):
            cause = cause.reason
        else:
            break

    if isinstance(cause, FileNotFoundError):
        kind = "runtime_missing"
        message = "语音服务的网络组件不完整，请更新到最新软件包后重试。"
    elif isinstance(cause, ssl.SSLError):
        kind = "tls"
        message = "与语音服务建立加密连接失败。请检查系统时间，以及代理或 VPN 是否拦截了 HTTPS，再重试。"
    elif isinstance(cause, socket.gaierror):
        kind = "dns"
        message = "当前网络无法解析语音服务域名。请检查 DNS、代理或 VPN 连接后重试。"
    elif isinstance(cause, (TimeoutError, socket.timeout)) or getattr(cause, "errno", None) == errno.ETIMEDOUT:
        kind = "timeout"
        message = f"连接或接收语音结果时超过 {REQUEST_TIMEOUT_SECONDS} 秒无响应。可缩短录音，并检查网络、代理或 VPN 后重试。"
    elif isinstance(cause, ConnectionRefusedError):
        kind = "connection_refused"
        message = "网络已找到语音服务，但连接被拒绝。请检查代理、VPN 或当前网络策略后重试。"
    elif isinstance(cause, (ConnectionResetError, BrokenPipeError)):
        kind = "connection_reset"
        message = "上传或等待语音结果时连接中断。请检查网络稳定性后重试；录音没有自动重发。"
    elif isinstance(cause, OSError) and getattr(cause, "errno", None) in {errno.ENETUNREACH, errno.EHOSTUNREACH}:
        kind = "network_unreachable"
        message = "当前网络无法连接语音服务。请检查网络、代理或 VPN 后重试。"
    else:
        kind = "network"
        message = "语音服务暂时无法连接。请检查网络、代理或 VPN 后重试。"
    diagnostics = {"networkCause": kind, "transportException": type(error).__name__,
                   "reasonException": type(cause).__name__}
    for name, source in (("systemError", "errno"), ("certificateVerifyCode", "verify_code")):
        value = getattr(cause, source, None)
        if isinstance(value, int):
            diagnostics[name] = value
    code = "voice_runtime_incomplete" if kind == "runtime_missing" else "voice_network_failed"
    return SpeechError(code, message,
                       provider=item["provider"], model=item["model"], region=item["region"],
                       timeoutSeconds=REQUEST_TIMEOUT_SECONDS, **diagnostics)


def check(condition, code, message):
    if not condition:
        raise SpeechError(code, message)


def profile(payload):
    provider = payload.get("provider", "qwen-asr")
    check(provider in CATALOG, "voice_model_unsupported", "请选择支持语音转文字的服务。")
    catalog = CATALOG[provider]
    region = payload.get("region", next(iter(catalog["regions"])))
    model = payload.get("model", catalog["models"][0])
    check(region in catalog["regions"] and model in catalog["models"],
          "voice_model_unsupported", "此服务或模型尚未提供语音识别，请选择列表中的语音模型。")
    return {"provider": provider, "region": region, "model": model}


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".voice-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SpeechSettings:
    def __init__(self, state_dir):
        self.root = Path(state_dir)
        self.location = self.root / "voice-settings.json"

    def key_path(self, provider):
        check(provider in CATALOG, "voice_model_unsupported", "语音服务无效。")
        return self.root / "voice-keys" / (provider + ".key")

    def key(self, provider):
        path = self.key_path(provider)
        if not path.exists():
            return None
        try:
            check(path.stat().st_size <= 4096, "voice_key_invalid", "语音 Key 无法读取，请重新填写并保存。")
            key = path.read_text(encoding="utf-8")
            check(bool(key) and all(33 <= ord(c) <= 126 for c in key), "voice_key_invalid", "语音 Key 无法读取，请重新填写并保存。")
            return key
        except (OSError, UnicodeError):
            raise SpeechError("voice_key_invalid", "语音 Key 无法读取，请重新填写并保存。") from None

    def load(self):
        if not self.location.exists():
            return {"active": "qwen-asr", "profiles": {}}
        try:
            check(self.location.stat().st_size <= 16384, "voice_settings_invalid", "语音配置无法读取，请重新保存连接。")
            value = json.loads(self.location.read_text(encoding="utf-8"))
            check(isinstance(value, dict) and value.get("active") in CATALOG and isinstance(value.get("profiles"), dict),
                  "voice_settings_invalid", "语音配置无法读取，请重新保存连接。")
            return {"active": value["active"], "profiles": {p: profile(v) for p, v in value["profiles"].items() if p in CATALOG and v.get("provider") == p}}
        except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
            raise SpeechError("voice_settings_invalid", "语音配置无法读取，请重新保存连接。") from None

    def get(self):
        value = self.load()
        profiles = {}
        for provider in CATALOG:
            item = value["profiles"].get(provider) or profile({"provider": provider})
            try:
                profiles[provider] = {**item, "hasKey": bool(self.key(provider)), "supportsTranscription": True}
            except SpeechError:
                profiles[provider] = {**item, "hasKey": False, "supportsTranscription": True,
                                      "credentialError": "语音 Key 无法读取，请重新填写并保存。"}
        return {**profiles[value["active"]], "profiles": profiles,
                "catalog": [{"provider": p, "name": c["name"], "models": c["models"], "regions": list(c["regions"])} for p, c in CATALOG.items()]}

    def save(self, payload):
        item = profile(payload)
        value = self.load()
        provider = item["provider"]
        path = self.key_path(provider)
        old_bytes = path.read_bytes() if path.exists() else None
        supplied = payload.get("apiKey")
        check(supplied is None or isinstance(supplied, str), "voice_key_invalid", "请填写有效的语音 API Key。")
        key = supplied.strip() if isinstance(supplied, str) else None
        check(not key or len(key) <= 4096 and all(33 <= ord(c) <= 126 for c in key), "voice_key_invalid", "请填写有效的语音 API Key。")
        check(bool(key) or bool(self.key(provider)), "voice_key_missing", "请先填写此语音服务的 API Key。")
        try:
            if key:
                atomic(path, key.encode("utf-8"))
            value["profiles"][provider] = item
            value["active"] = provider
            atomic(self.location, json.dumps(value, ensure_ascii=False).encode("utf-8"))
        except OSError:
            if key:
                if old_bytes is not None:
                    atomic(path, old_bytes)
                else:
                    path.unlink(missing_ok=True)
            raise SpeechError("voice_save_failed", "语音连接没有保存成功，请重试。") from None
        return self.get()

    def reveal(self, payload):
        provider = profile(payload)["provider"]
        return {"provider": provider, "apiKey": self.key(provider) or ""}

    def delete(self, payload):
        provider = profile(payload)["provider"]
        try:
            self.key_path(provider).unlink(missing_ok=True)
        except OSError:
            raise SpeechError("voice_save_failed", "语音 Key 未移除，请重试。") from None
        return self.get()


def decode_audio(audio):
    check(isinstance(audio, dict), "voice_audio_invalid", "录音格式无效，请重新录制。")
    data_url = audio.get("dataUrl")
    check(isinstance(data_url, str) and data_url.startswith("data:audio/wav;base64,") and len(data_url) <= MAX_AUDIO * 4 // 3 + 64,
          "voice_audio_invalid", "录音格式或大小不支持，请重新录制。")
    try:
        data = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        check(44 <= len(data) <= MAX_AUDIO, "voice_audio_invalid", "录音为空或过大，请重新录制。")
        with wave.open(io.BytesIO(data), "rb") as source:
            check(source.getcomptype() == "NONE" and source.getsampwidth() == 2 and source.getnchannels() == 1 and
                  8000 <= source.getframerate() <= 48000, "voice_audio_invalid", "录音格式不支持，请重新录制。")
            seconds = source.getnframes() / source.getframerate()
            frames = source.readframes(source.getnframes())
            check(0.15 <= seconds <= MAX_SECONDS and len(frames) == source.getnframes() * 2,
                  "voice_audio_invalid", "录音过短、超出一分钟或不完整，请重新录制。")
            peak = max((abs(int.from_bytes(frames[i:i+2], "little", signed=True)) for i in range(0, len(frames), 2)), default=0)
            check(peak >= 24, "voice_silent", "没有收到有效声音，请检查麦克风后重试。")
        return data, round(seconds * 1000)
    except (binascii.Error, wave.Error, EOFError, ValueError):
        raise SpeechError("voice_audio_invalid", "录音无法读取，请重新录制。") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SpeechError("voice_network_failed", "语音服务返回了不受支持的跳转，请检查连接。")


def request_body(item, audio_bytes):
    provider, model = item["provider"], item["model"]
    base = CATALOG[provider]["regions"][item["region"]]
    if provider == "qwen-asr":
        data_url = "data:audio/wav;base64," + base64.b64encode(audio_bytes).decode("ascii")
        body = {"model": model, "messages": [{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": data_url}}]}],
                "stream": False, "asr_options": {"enable_itn": True}}
        return base + "/chat/completions", json.dumps(body).encode(), "application/json"
    boundary = "studio-voice-" + uuid.uuid4().hex
    parts = []
    fields = [("model", model), ("response_format", "json")]
    if provider == "minimax-asr":
        # ASR streams response text only after uploading a complete recording;
        # dictation uses one complete, bounded JSON result, never a live stream.
        fields.append(("stream", "false"))
    for name, value in fields:
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode())
    parts += [(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="dictation.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode(),
              audio_bytes, (f"\r\n--{boundary}--\r\n").encode()]
    route = "/speech_to_text" if provider == "minimax-asr" else "/audio/transcriptions"
    return base + route, b"".join(parts), "multipart/form-data; boundary=" + boundary


def transcribe(settings, payload, opener=None):
    request_id = payload.get("requestId")
    check(isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id), "voice_request_invalid", "语音请求编号无效。")
    metadata = settings.get()
    check(payload.get("expectedProvider") == metadata["provider"] and payload.get("expectedModel") == metadata["model"] and
          payload.get("expectedRegion") == metadata["region"],
          "voice_settings_changed", "语音模型已改变，请重新录制。")
    key = settings.key(metadata["provider"])
    check(bool(key), "voice_key_missing", "先在模型配置中保存语音识别连接，再使用语音输入。")
    data, duration_ms = decode_audio(payload.get("audio"))
    url, body, content_type = request_body(metadata, data)
    request = urllib.request.Request(url, data=body, headers={"Authorization": "Bearer " + key,
                                                           "Content-Type": content_type, "Accept": "application/json"})
    try:
        with (opener or urllib.request.build_opener(NoRedirect())).open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE + 1)
            check(len(raw) <= MAX_RESPONSE, "voice_response_large", "语音回复过长，已停止识别，请缩短录音后重试。")
        result = json.loads(raw)
        check(isinstance(result, dict), "voice_incomplete", "语音服务返回了无法识别的结果，请重试。")
        if metadata["provider"] == "minimax-asr":
            # A gateway error must never be mistaken for a transcription, even
            # if it includes a stray text field. Do not surface provider bodies.
            status = result.get("base_resp")
            check(not result.get("error") and
                  (status is None or isinstance(status, dict) and status.get("status_code") == 0),
                  "voice_service_failed", "语音服务未完成识别，请检查连接和额度后重试。")
        if metadata["provider"] == "qwen-asr":
            choices = result.get("choices")
            check(isinstance(choices, list) and len(choices) == 1 and choices[0].get("finish_reason") == "stop",
                  "voice_incomplete", "语音识别未完整结束，请重试。")
            text = choices[0].get("message", {}).get("content")
        else:
            text = result.get("text")
        check(isinstance(text, str) and len(text) <= 4000, "voice_incomplete", "语音识别结果不完整或太长，请缩短录音后重试。")
        text = text.strip()
        check(bool(text), "voice_empty", "没有识别到文字，请重新录制。")
        return {"requestId": request_id, "text": text, "provider": metadata["provider"], "model": metadata["model"], "durationMs": duration_ms}
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise SpeechError("voice_auth_failed", "语音服务拒绝连接，请检查 Key、接口区域和模型权限。") from None
        if error.code == 429:
            raise SpeechError("voice_rate_limit", "语音服务额度不足或请求过多，请稍后再试。") from None
        if error.code in (408, 504):
            raise SpeechError("voice_service_timeout", "语音服务端处理超时。请缩短录音或稍后重试；请求不会自动重发。",
                               provider=metadata["provider"], model=metadata["model"], region=metadata["region"],
                               httpStatus=error.code) from None
        raise SpeechError("voice_service_failed", "语音服务暂时未完成识别，请稍后重试。") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise network_failure(error, metadata) from None
    except (ValueError, TypeError, KeyError, AttributeError):
        raise SpeechError("voice_incomplete", "语音服务返回了无法识别的结果，请重试。") from None
