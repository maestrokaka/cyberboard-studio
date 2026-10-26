"""R6 short audio commands, implemented from observed official wire behavior.

No speculative GETs: the firmware's current audio settings cannot be queried by
the known protocol. A successful SET echo is kept as a local historical record.
This module never sends JSON_START, modifies keymaps, or starts a microphone.
"""
from __future__ import annotations
import contextlib
import json
import time
import uuid
from datetime import datetime, timezone


class R6AudioError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


OPTIONS = {
    "speaker": (0x06, {0: "关闭", 1: "仅左声道", 2: "仅右声道", 3: "左右声道"}),
    "noise_reduction": (0x08, {0: "最高", 1: "稍弱", 2: "关闭"}),
    "mic_tone": (0x09, {1: "常规", 2: "高亮", 3: "低频饱满"}),
    "mic_direction": (0x0A, {21: "前向", 32: "后向", 48: "全向"}),
}


def _identity(bridge, payload):
    device = bridge.discover(payload)
    if device is None:
        raise R6AudioError("device_missing", "请通过 USB 连接 R6；若官网占用串口，请先在官网断开。")
    return device, bridge.device_dict(device)


def _supported(identity):
    return identity.product_id.upper() == "AM01R6"


def _check_expected(identity, expected):
    fields = {"port": identity.port, "productId": identity.product_id, "firmware": identity.version}
    if not isinstance(expected, dict) or any(expected.get(k) != v for k, v in fields.items()):
        raise R6AudioError("device_changed", "设备或固件已改变，请刷新声音页面后再设置。")


@contextlib.contextmanager
def _serial(bridge, identity):
    device = bridge.cli["cb_device"]
    serial_module = bridge.cli["cb_settime"].serial
    try:
        stream = serial_module.Serial(identity.port, baudrate=device.BAUD, timeout=0.2,
                                      write_timeout=2, exclusive=True)
    except OSError:
        raise R6AudioError("audio_serial_busy", "无法打开键盘，请关闭官网或其他配置软件后再试。") from None
    try:
        time.sleep(0.1)
        stream.reset_input_buffer()
        yield stream
    finally:
        stream.close()


def request(bridge, stream, command, value=None, timeout=2, *, clock=time.monotonic):
    protocol = bridge.cli["cb_protocol"]
    packet = protocol.build_frame(7, command, b"" if value is None else bytes([value]))
    if stream.write(packet) != 64:
        raise R6AudioError("audio_write_incomplete", "声音指令未完整发送，实际设置待确认。", state="unknown")
    stream.flush()
    pending = bytearray()
    deadline = clock() + timeout
    while clock() < deadline:
        pending.extend(stream.read(64 - len(pending)))
        if len(pending) < 64:
            continue
        frame, pending = bytes(pending[:64]), pending[64:]
        if not protocol.crc_ok(frame):
            raise R6AudioError("audio_crc_failed", "设备应答校验失败，实际设置待确认。", state="unknown")
        if frame[:2] == bytes([7, command]):
            return frame
    raise R6AudioError("audio_timeout", "未收到声音设置回执；指令可能已生效，请重连后重新明确设置。", state="unknown")


def _history_path(bridge):
    return bridge.state_dir / "r6-audio-last-confirmed.json"


def _history(bridge, device):
    try:
        path = _history_path(bridge)
        if path.stat().st_size > 32768:
            return {}
        result = json.loads(path.read_text(encoding="utf-8"))
        stable = {k: device.get(k) for k in ("productId", "firmware", "port")}
        records = result.get("settings", {}) if result.get("device") == stable else {}
        return records if isinstance(records, dict) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _remember(bridge, device, setting, value, state):
    records = _history(bridge, device)
    records[setting] = {"value": value, "state": state,
                        "confirmedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    # The record is never presented as the device's live state.
    bridge.state_dir.mkdir(parents=True, exist_ok=True)
    path = _history_path(bridge)
    temporary = path.with_name(".audio-" + uuid.uuid4().hex + ".tmp")
    try:
        stable = {k: device.get(k) for k in ("productId", "firmware", "port")}
        temporary.write_text(json.dumps({"version": 1, "device": stable, "settings": records}, ensure_ascii=False), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def status(bridge, payload):
    identity, device = _identity(bridge, payload)
    return {"connected": True, "device": device, "supportsAudio": _supported(identity),
            "settings": dict.fromkeys(OPTIONS), "lastConfirmed": _history(bridge, device),
            "verification": "unknown", "canReadSettings": False,
            "directionReference": "官网前向/后向命名；具体物理方向需按当前固件实测。"}


def set_setting(bridge, payload):
    setting, value = payload.get("setting"), payload.get("value")
    if setting not in OPTIONS or type(value) is not int or value not in OPTIONS[setting][1]:
        raise R6AudioError("invalid_audio_setting", "声音设置参数无效。")
    identity, device = _identity(bridge, payload)
    if not _supported(identity):
        raise R6AudioError("audio_unsupported", "声音硬件设置目前仅支持 CYBERBOARD R6。")
    _check_expected(identity, payload.get("expectedDevice"))
    command = OPTIONS[setting][0]
    # Persist uncertainty before the first potentially mutating byte is sent.
    _remember(bridge, device, setting, None, "unknown")
    try:
        with _serial(bridge, identity) as stream:
            response = request(bridge, stream, command, value)
        if response[2] != value or (setting != "speaker" and response[3] != 0):
            raise R6AudioError("audio_rejected", "设备没有确认此声音设置，实际状态待确认。", state="unknown")
        _remember(bridge, device, setting, value, "acknowledged")
    except R6AudioError:
        raise
    except OSError:
        raise R6AudioError("audio_io_failed", "声音设置过程中连接中断，实际状态待确认。", state="unknown") from None
    return {"setting": setting, "value": value, "state": "acknowledged", "verification": "set_echo",
            "acousticVerified": False, "canReadSettings": False, "device": device}


def calibrate(bridge, payload, *, sleep=time.sleep, clock=time.monotonic):
    if payload.get("confirmCalibration") is not True or payload.get("nativeAudioActive") is not True:
        raise R6AudioError("calibration_not_prepared", "请在声音页面确认校准，并先将默认输出切换为 AIROHAChat。")
    identity, device = _identity(bridge, payload)
    if not _supported(identity):
        raise R6AudioError("audio_unsupported", "扬声器校准目前仅支持 R6。")
    _check_expected(identity, payload.get("expectedDevice"))
    _remember(bridge, device, "speaker", None, "unknown")
    try:
        with _serial(bridge, identity) as stream:
            protocol = bridge.cli["cb_protocol"]
            if stream.write(protocol.build_frame(7, 7)) != 64:
                raise R6AudioError("calibration_incomplete", "测试模式指令未完整发送，设备状态待确认。")
            stream.flush()
            response = request(bridge, stream, 6, 3)
            if response[2] != 3:
                raise R6AudioError("calibration_rejected", "设备未确认双声道，已停止校准。")
            _remember(bridge, device, "speaker", 3, "acknowledged")
            bridge.event("audio-calibration", message="保持 AIROHAChat 连接，正在校准…")
            sleep(10)
            deadline = clock() + 15
            while clock() < deadline:
                response = request(bridge, stream, 4, timeout=min(10, deadline - clock()), clock=clock)
                if response[2] == 1:
                    left = int.from_bytes(response[4:6], "little") / 1024
                    right = int.from_bytes(response[6:8], "little") / 1024
                    return {"state": "completed", "phase": "complete", "passed": response[3] == 0 and 5 <= left <= 6 and 5 <= right <= 6,
                            "leftOhms": left, "rightOhms": right, "device": device,
                            "speakerMask": 3, "testModeExitConfirmed": False,
                            "message": "校准已结束；保持双声道，测试模式退出由固件处理，尚无独立退出回执。"}
                if response[2] != 0:
                    raise R6AudioError("calibration_rejected", "设备返回了无法识别的校准状态。")
                sleep(0.5)
            raise R6AudioError("calibration_timeout", "扬声器校准未在期限内完成，设备状态待确认。", state="unknown")
    except OSError:
        raise R6AudioError("calibration_io_failed", "校准连接中断，请重新连接键盘。", state="unknown") from None


def dispatch(bridge, action, payload):
    return {"r6AudioStatus": status, "r6AudioSet": set_setting, "r6AudioCalibrate": calibrate}[action](bridge, payload)
