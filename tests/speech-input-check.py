"""Offline ASR protocols and local profiles; synthetic audio and fake credentials only."""
import base64
import errno
from email.parser import BytesParser
from email.policy import default as email_policy
import importlib.util
import io
import json
import socket
import ssl
import tempfile
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("speech_input", ROOT / "backend/speech_input.py")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


def audio(seconds=1, silent=False):
    output = io.BytesIO()
    with wave.open(output, "wb") as source:
        source.setnchannels(1)
        source.setsampwidth(2)
        source.setframerate(16000)
        source.writeframes((b"\0\0" if silent else b"\x00\x10") * int(16000 * seconds))
    return {"dataUrl": "data:audio/wav;base64," + base64.b64encode(output.getvalue()).decode(), "durationMs": seconds * 1000}


class Response(io.BytesIO):
    pass


class Opener:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.reply, Exception):
            raise self.reply
        return Response(self.reply if isinstance(self.reply, bytes) else json.dumps(self.reply).encode())


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = s.SpeechSettings(self.temp.name)
        self.settings.save({"provider": "qwen-asr", "apiKey": "fake-qwen-key"})
        self.payload = {"requestId": "voice-offline-1", "audio": audio(), "expectedProvider": "qwen-asr", "expectedModel": "qwen3-asr-flash", "expectedRegion": "china"}

    def tearDown(self):
        self.temp.cleanup()

    def test_metadata_never_contains_keys(self):
        value = self.settings.get()
        self.assertTrue(value["hasKey"])
        self.assertNotIn("fake-qwen-key", json.dumps(value))
        self.assertNotIn("fake-qwen-key", self.settings.location.read_text())

    def test_separate_plain_profiles_and_reveal_delete(self):
        self.settings.save({"provider": "openai-asr", "model": "gpt-transcribe", "apiKey": "fake-openai-key"})
        self.settings.save({"provider": "minimax-asr", "apiKey": "fake-minimax-key"})
        self.assertEqual(self.settings.get()["provider"], "minimax-asr")
        self.assertEqual(self.settings.get()["region"], "china")
        self.assertNotIn("fake-minimax-key", json.dumps(self.settings.get()))
        self.assertEqual(self.settings.key("minimax-asr"), "fake-minimax-key")
        self.assertEqual(self.settings.key("qwen-asr"), "fake-qwen-key")
        self.assertEqual(self.settings.reveal({"provider": "openai-asr"})["apiKey"], "fake-openai-key")
        self.settings.delete({"provider": "openai-asr"})
        self.assertIsNone(self.settings.key("openai-asr"))
        self.assertEqual(self.settings.key("qwen-asr"), "fake-qwen-key")
        self.assertEqual(self.settings.key("minimax-asr"), "fake-minimax-key")

    def test_save_rolls_back_key_on_metadata_failure(self):
        actual = s.atomic
        def failure(path, data):
            if Path(path).name == "voice-settings.json":
                raise OSError("offline disk full")
            actual(path, data)
        with patch.object(s, "atomic", side_effect=failure), self.assertRaises(s.SpeechError):
            self.settings.save({"provider": "qwen-asr", "apiKey": "fake-replacement"})
        self.assertEqual(self.settings.key("qwen-asr"), "fake-qwen-key")

    def test_unsupported_model_region_and_key(self):
        for payload in ({"provider": "kimi-code"}, {"provider": "qwen-asr", "model": "k3"}, {"provider": "openai-asr", "region": "china"}, {"provider": "qwen-asr", "apiKey": "line\nbreak"},
                        {"provider": "minimax-asr", "model": "MiniMax-M3"}, {"provider": "minimax-asr", "region": "custom"}):
            with self.assertRaises(s.SpeechError):
                self.settings.save(payload)

    def test_audio_uses_decoded_duration_not_claim(self):
        value = audio()
        value["durationMs"] = 90000
        self.assertEqual(s.decode_audio(value)[1], 1000)

    def test_audio_rejects_invalid_short_silent_and_long(self):
        for value in ({"dataUrl": "https://private.example/file.wav"}, {"dataUrl": "data:audio/wav;base64,!"}, audio(.01), audio(1, True), audio(61)):
            with self.assertRaises(s.SpeechError):
                s.decode_audio(value)

    def test_qwen_request_schema_and_stop(self):
        opener = Opener({"choices": [{"finish_reason": "stop", "message": {"content": "蓝紫对撞，轴灯变黄。"}}]})
        result = s.transcribe(self.settings, self.payload, opener)
        self.assertEqual(result["text"], "蓝紫对撞，轴灯变黄。")
        self.assertEqual(result["durationMs"], 1000)
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        body = json.loads(request.data)
        self.assertEqual(body["messages"][0]["content"][0]["type"], "input_audio")
        self.assertTrue(body["messages"][0]["content"][0]["input_audio"]["data"].startswith("data:audio/wav;base64,"))
        self.assertFalse(body["stream"])
        self.assertEqual(timeout, 60)
        self.assertNotIn("audio", result)

    def test_openai_multipart_and_text(self):
        self.settings.save({"provider": "openai-asr", "apiKey": "fake-openai-key"})
        payload = {**self.payload, "expectedProvider": "openai-asr", "expectedModel": "gpt-transcribe", "expectedRegion": "global"}
        opener = Opener({"text": "一束红光。"})
        self.assertEqual(s.transcribe(self.settings, payload, opener)["text"], "一束红光。")
        request = opener.calls[0][0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/audio/transcriptions")
        self.assertIn(b'name="model"\r\n\r\ngpt-transcribe', request.data)
        self.assertIn(b'filename="dictation.wav"', request.data)
        self.assertIn(b"RIFF", request.data)
        self.assertNotIn(b"fake-openai-key", request.data)

    def minimax_payload(self, region="china"):
        self.settings.save({"provider": "minimax-asr", "region": region, "apiKey": "fake-minimax-key"})
        return {**self.payload, "expectedProvider": "minimax-asr", "expectedModel": "asr-1.0", "expectedRegion": region}

    def test_minimax_catalog_and_official_regions(self):
        self.assertEqual(s.profile({"provider": "minimax-asr"}),
                         {"provider": "minimax-asr", "region": "china", "model": "asr-1.0"})
        catalog = next(item for item in self.settings.get()["catalog"] if item["provider"] == "minimax-asr")
        self.assertEqual(catalog["models"], ["asr-1.0"])
        self.assertEqual(catalog["regions"], ["china", "global"])

    def test_minimax_complete_multipart_and_negative_instruction(self):
        payload = self.minimax_payload()
        spoken = "请打开 Spotify，播放周杰伦的晴天，不要修改键盘配置。"
        opener = Opener({"text": spoken, "duration": 1.0, "trace_id": "synthetic-not-persisted"})
        result = s.transcribe(self.settings, payload, opener)
        self.assertEqual(result["text"], spoken)
        self.assertEqual(result["provider"], "minimax-asr")
        self.assertEqual(result["model"], "asr-1.0")
        self.assertEqual(result["durationMs"], 1000)
        self.assertNotIn("trace_id", result)
        self.assertNotIn("audio", result)
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, "https://api.minimax.cn/v1/speech_to_text")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-minimax-key")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(timeout, 60)
        multipart = BytesParser(policy=email_policy).parsebytes(
            ("Content-Type: " + request.get_header("Content-type") + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + request.data)
        fields = {part.get_param("name", header="content-disposition"): part for part in multipart.iter_parts()}
        self.assertEqual(set(fields), {"model", "file", "response_format", "stream"})
        for name, value in (("model", "asr-1.0"), ("response_format", "json"), ("stream", "false")):
            self.assertEqual(fields[name].get_payload(decode=True).decode(), value)
        self.assertEqual(fields["file"].get_filename(), "dictation.wav")
        self.assertEqual(fields["file"].get_content_type(), "audio/wav")
        self.assertEqual(fields["file"].get_payload(decode=True), s.decode_audio(payload["audio"])[0])
        self.assertNotIn(b"fake-minimax-key", request.data)

    def test_minimax_international_route(self):
        payload = self.minimax_payload("global")
        opener = Opener({"text": "只制作预览，不同步。", "duration": 1})
        self.assertEqual(s.transcribe(self.settings, payload, opener)["text"], "只制作预览，不同步。")
        self.assertEqual(opener.calls[0][0].full_url, "https://api.minimax.io/v1/speech_to_text")

    def test_minimax_bad_complete_results_are_not_accepted(self):
        payload = self.minimax_payload()
        for reply in ({"text": ""}, {"text": "  "}, {"text": "x" * 4001}, {"text": None},
                      {"text": ["not text"]}, [], {"duration": 1},
                      {"text": "not successful", "error": {"message": "fake-minimax-key"}},
                      {"text": "not successful", "base_resp": {"status_code": 1004, "status_msg": "fake-minimax-key"}},
                      {"text": "not successful", "base_resp": "invalid"},
                      b"data: {\"delta\":\"partial\",\"finish\":false}\n\n",
                      b"x" * (s.MAX_RESPONSE + 1), b"{\"text\":\"truncated"):
            with self.subTest(reply_type=type(reply).__name__), self.assertRaises(s.SpeechError) as caught:
                s.transcribe(self.settings, payload, Opener(reply))
            self.assertNotIn("fake-minimax-key", str(caught.exception))

    def test_minimax_configuration_change_prevents_upload(self):
        payload = self.minimax_payload()
        self.settings.save({"provider": "qwen-asr"})
        opener = Opener({"text": "late"})
        with self.assertRaises(s.SpeechError) as caught:
            s.transcribe(self.settings, payload, opener)
        self.assertEqual(caught.exception.code, "voice_settings_changed")
        self.assertEqual(opener.calls, [])

    def test_minimax_service_failures_are_bounded_and_redacted(self):
        payload = self.minimax_payload()
        for status in (400, 401, 403, 413, 429, 500):
            error = urllib.error.HTTPError("https://api.minimax.cn/v1/speech_to_text", status,
                                           "fake-minimax-key", {}, io.BytesIO(b"private response"))
            with self.subTest(status=status), self.assertRaises(s.SpeechError) as caught:
                s.transcribe(self.settings, payload, Opener(error))
            self.assertNotIn("fake-minimax-key", str(caught.exception))
            self.assertNotIn("private", str(caught.exception))
        for status in (408, 504):
            error = urllib.error.HTTPError("https://api.minimax.cn/v1/speech_to_text", status,
                                           "fake-minimax-key", {}, io.BytesIO(b"private response"))
            with self.assertRaises(s.SpeechError) as caught:
                s.transcribe(self.settings, payload, Opener(error))
            self.assertEqual(caught.exception.code, "voice_service_timeout")
            self.assertEqual(caught.exception.details["httpStatus"], status)
            self.assertNotIn("fake-minimax-key", str(caught.exception))
            self.assertNotIn("private", str(caught.exception))
        failures = (
            (FileNotFoundError(errno.ENOENT, "fake-minimax-key"), "runtime_missing"),
            (urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, "fake-minimax-key")), "dns"),
            (TimeoutError("fake-minimax-key"), "timeout"),
            (urllib.error.URLError(ssl.SSLError("fake-minimax-key")), "tls"),
            (ConnectionRefusedError(errno.ECONNREFUSED, "fake-minimax-key"), "connection_refused"),
            (ConnectionResetError(errno.ECONNRESET, "fake-minimax-key"), "connection_reset"),
            (OSError(errno.ENETUNREACH, "fake-minimax-key"), "network_unreachable"),
            (urllib.error.URLError("fake-minimax-key"), "network"),
        )
        for error, cause in failures:
            with self.assertRaises(s.SpeechError) as caught:
                s.transcribe(self.settings, payload, Opener(error))
            self.assertEqual(caught.exception.code, "voice_runtime_incomplete" if cause == "runtime_missing" else "voice_network_failed")
            self.assertEqual(caught.exception.details["networkCause"], cause)
            self.assertEqual(caught.exception.details["provider"], "minimax-asr")
            self.assertEqual(caught.exception.details["model"], "asr-1.0")
            self.assertEqual(caught.exception.details["region"], "china")
            self.assertEqual(caught.exception.details["timeoutSeconds"], s.REQUEST_TIMEOUT_SECONDS)
            self.assertNotIn("fake-minimax-key", str(caught.exception))
            self.assertNotIn("fake-minimax-key", json.dumps(caught.exception.details))

    def test_minimax_profile_and_key_survive_reload(self):
        self.minimax_payload("global")
        fresh = s.SpeechSettings(self.temp.name)
        self.assertEqual(fresh.get()["provider"], "minimax-asr")
        self.assertEqual(fresh.get()["region"], "global")
        self.assertEqual(fresh.get()["model"], "asr-1.0")
        self.assertEqual(fresh.reveal({"provider": "minimax-asr"})["apiKey"], "fake-minimax-key")
        self.assertEqual(fresh.key_path("minimax-asr").stat().st_mode & 0o777, 0o600)
        fresh.delete({"provider": "minimax-asr"})
        self.assertFalse(fresh.get()["hasKey"])
        self.assertEqual(fresh.key("qwen-asr"), "fake-qwen-key")

    def test_incomplete_and_response_limits(self):
        for reply in ({"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}, {"choices": []}, {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}, b"x" * (s.MAX_RESPONSE + 1), b"not JSON"):
            with self.assertRaises(s.SpeechError):
                s.transcribe(self.settings, self.payload, Opener(reply))

    def test_configuration_change_prevents_network(self):
        opener = Opener({})
        for field in ("expectedProvider", "expectedModel", "expectedRegion"):
            with self.assertRaises(s.SpeechError):
                s.transcribe(self.settings, {**self.payload, field: "different"}, opener)
        self.assertEqual(opener.calls, [])

    def test_http_error_does_not_echo_body_or_secret(self):
        for status in (401, 403, 429, 500):
            error = urllib.error.HTTPError("https://official.example", status, "fake-qwen-key", {}, io.BytesIO(b"sensitive audio response"))
            with self.assertRaises(s.SpeechError) as caught:
                s.transcribe(self.settings, self.payload, Opener(error))
            self.assertNotIn("fake-qwen-key", str(caught.exception))
            self.assertNotIn("sensitive", str(caught.exception))

    def test_no_redirect_with_authorization(self):
        with self.assertRaises(s.SpeechError):
            s.NoRedirect().redirect_request(None, None, 302, "", {}, "http://untrusted.example")


if __name__ == "__main__":
    unittest.main()
