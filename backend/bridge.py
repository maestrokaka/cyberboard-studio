#!/usr/bin/env python3
"""One-shot JSON-lines bridge to the locally installed Cyberboard CLI.

bootstrap/history/keymapCatalog are offline. detect/keymap are USB reads. plan/restorePlan/keymapPlan
prepare a reviewable full configuration; only execute writes that configuration.
initializePlan prepares a new full configuration when no previous record exists.
setTime writes the RTC only. LED state is always labelled last-written because
the device protocol cannot read LED pixels back.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import errno
import hashlib
import importlib
import io
import json
import math
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")
RGB_RE = re.compile(r"^#[a-fA-F0-9]{6}$")
KEY_RE = re.compile(r"^#[a-fA-F0-9]{8}$")
UNICODE_RE = re.compile(r"^#[a-fA-F0-9]{4}$")
SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9_.-]+\.json$")
RESERVED_LEDS = (57, 61, 74, 78, 82, 83, 84)
PLAN_LIFETIME_SECONDS = 30 * 60
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_WORKSPACE_BYTES = 32 * 1024 * 1024
INITIALIZATION_LIMITATIONS = (
    "键盘原灯效无法读取，也没有原完整配置备份；初始化后无法恢复未知的原灯效。",
    "内置模式（页面 0–4）使用官网标准配置，电量、马赛克与时钟默认启用；这不是键盘原来的设置。未分配的自定义槽将停用并写为黑色。",
    "仅原样保留 USB 读取的 1400 个键码；独立交换、换键表将清空，宏和其他未支持的功能无法保证保留。",
)
BUILTIN_NAMES = ("电量", "马赛克", "时钟", "文字", "流光")

# Source importlib tests and isolated Windows Python need the sibling modules.
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

import keymap_codec


class BridgeError(Exception):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def require(condition, code, message, **details):
    if not condition:
        raise BridgeError(code, message, **details)


def emit(value):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def configure_stdio():
    """The native hosts exchange UTF-8 JSON, regardless of Windows code page."""
    if sys.platform == "win32":
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="strict", newline="\n")


@contextlib.contextmanager
def operation_lock(path):
    """Serialize USB actions across app processes on both supported platforms.

    Windows serial handles are exclusive, but that alone cannot protect the
    complete plan/read/write/verify sequence. Lock byte zero for its whole
    lifetime; keep waiting through contention because a full transfer can
    exceed the ten-second retry window of msvcrt.LK_LOCK.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if sys.platform == "win32":
            import msvcrt
            stream.seek(0, io.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            while True:
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    time.sleep(0.1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def resolve_timezone(name):
    require(isinstance(name, str) and 0 < len(name) <= 128,
            "invalid_timezone", "所选时区无效。")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        # Windows does not ship an IANA database. The portable build includes
        # tzdata, so report an incomplete installation separately from a typo.
        try:
            ZoneInfo("UTC")
        except ZoneInfoNotFoundError:
            raise BridgeError("timezone_data_missing", "应用缺少时区数据库，请重新安装完整版本。") from error
        raise BridgeError("invalid_timezone", "所选时区无效。") from error
    except (ValueError, TypeError, KeyError) as error:
        raise BridgeError("invalid_timezone", "所选时区无效。") from error


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, value, *, compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=None if compact else 2,
                                    separators=(",", ":") if compact else None, allow_nan=False) + "\n")
            stream.flush()
            import os
            os.fsync(stream.fileno())
        tmp.chmod(0o600)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def load_cli():
    try:
        import cyberboard
    except ImportError as error:
        raise BridgeError("cli_unavailable", "未找到本机 Cyberboard CLI，请先安装。") from error
    directory = Path(cyberboard.__file__).resolve().parent / "_tools"
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    return {name: importlib.import_module(name) for name in
            ("cb_device", "cb_store", "cb_read", "cb_write", "cb_protocol", "cb_settime", "cb_keymap")}, cyberboard.__version__


def recognized(product_id):
    upper = (product_id or "").upper()
    return (upper == "AM01R6" or upper.startswith("CB")) and "DONGLE" not in upper


def integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, "invalid_input", f"{label}需要在 {low}–{high} 范围内。")
    return value


def validate_layers(fragment):
    require(isinstance(fragment, dict) and fragment.get("layer_num") == 7,
            "incomplete_keymap", "需要完整的 7 层键位配置。")
    layers = fragment.get("layer_data")
    require(isinstance(layers, list) and len(layers) == 7,
            "incomplete_keymap", "键位配置不完整。")
    for index, layer in enumerate(layers):
        codes = layer.get("layer") if isinstance(layer, dict) else None
        require(isinstance(codes, list) and len(codes) == 200 and
                all(isinstance(code, str) and KEY_RE.fullmatch(code) for code in codes),
                "incomplete_keymap", "键位读取不完整，未进行写入。", layer=index)
    return fragment


def matrix(fragment):
    validate_layers(fragment)
    return b"".join(bytes.fromhex(code[1:]) for layer in fragment["layer_data"] for code in layer["layer"])


def validate_animation(frames, count, label, *, allow_empty=False):
    minimum = 0 if allow_empty else 1
    require(isinstance(frames, list) and minimum <= len(frames) <= 255,
            "invalid_animation", f"{label}需要 {minimum}–255 帧。")
    for index, frame in enumerate(frames):
        require(isinstance(frame, list) and len(frame) == count,
                "invalid_animation", f"{label}第 {index + 1} 帧需要 {count} 个颜色。")
        require(all(isinstance(color, str) and RGB_RE.fullmatch(color) for color in frame),
                "invalid_animation", f"{label}包含无效颜色，请使用 #RRGGBB。")
        if count == 90:
            require(all(frame[position].upper() == "#000000" for position in RESERVED_LEDS),
                    "reserved_led", "轴灯的保留位置必须为黑色。", frame=index)


def page_for(config, slot):
    pages = [page for page in config.get("page_data", []) if page.get("page_index") == slot + 4]
    require(len(pages) == 1, "invalid_baseline", f"本机配置缺少自定义 {slot}，无法安全同步。")
    return pages[0]


def page_at(config, index):
    pages = [page for page in config.get("page_data", []) if isinstance(page, dict) and page.get("page_index") == index]
    require(len(pages) == 1, "invalid_baseline", f"本机配置缺少页面 {index}，无法安全同步。")
    return pages[0]


def nonzero(value):
    if value is None or value == "":
        return False
    if isinstance(value, str):
        try:
            return int(value) != 0
        except ValueError:
            return True
    return bool(value)


def substantive(value):
    """Only known unencoded feature containers use this; metadata is ignored."""
    if isinstance(value, dict):
        return any(substantive(item) for key, item in value.items() if key != "//")
    if isinstance(value, list):
        return bool(value)
    return nonzero(value)


def unsupported_write_paths(config):
    """Known active features omitted by the current full-config encoder."""
    if not isinstance(config, dict):
        return []
    paths = []
    for field in ("Fn_key", "MACRO_key", "tab_key", "macro_key", "ph_key"):
        if substantive(config.get(field)):
            paths.append(f"/{field}")
        count = f"{field}_num"
        if nonzero(config.get(count)):
            paths.append(f"/{count}")
    for field in ("HATSU", "hatsu"):
        if substantive(config.get(field)):
            paths.append(f"/{field}")

    def spotlight(container, prefix):
        if not isinstance(container, dict) or "spotlight_frames" not in container:
            return
        group = container["spotlight_frames"]
        if substantive(group):
            paths.append(f"{prefix}/spotlight_frames")

    spotlight(config, "")
    pages = config.get("page_data", [])
    if isinstance(pages, list):
        for index, page in enumerate(pages):
            spotlight(page, f"/page_data/{index}")
    return paths


def unsafe_wire_flag_paths(config):
    paths = []

    def inspect(container, field, prefix):
        if isinstance(container, dict) and field in container and type(container[field]) not in (bool, int):
            paths.append(f"{prefix}/{field}")

    inspect(config.get("key_layer"), "valid", "/key_layer")
    for index, page in enumerate(config.get("page_data", [])):
        if not isinstance(page, dict):
            continue
        prefix = f"/page_data/{index}"
        inspect(page, "valid", prefix)
        inspect(page.get("color"), "default", f"{prefix}/color")
        for field in ("word_page", "frames", "keyframes"):
            inspect(page.get(field), "valid", f"{prefix}/{field}")
    return paths


def require_supported_write(config):
    paths = unsupported_write_paths(config)
    require(not paths, "unsupported_config_features",
            "这份 JSON 含有当前写入器无法保留的功能。完整内容仍可读取与导出；请使用官方工具处理这些功能。",
            unsupportedPaths=paths)
    flags = unsafe_wire_flag_paths(config)
    require(not flags, "ambiguous_wire_flags", "配置的启用标记不是布尔值或整数，写入可能错误开启模式。请先通过可信工具修正。",
            unsupportedPaths=flags)


def configuration_diff(before, after, path=""):
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        differences = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if key not in before:
                differences.append({"path": child, "before": None, "after": copy.deepcopy(after[key])})
            elif key not in after:
                differences.append({"path": child, "before": copy.deepcopy(before[key]), "after": None})
            else:
                differences.extend(configuration_diff(before[key], after[key], child))
        return differences
    return [{"path": path, "before": copy.deepcopy(before), "after": copy.deepcopy(after)}]


def overlay_fields(current, replacement):
    for field, value in replacement.items():
        if isinstance(value, dict) and isinstance(current.get(field), dict):
            overlay_fields(current[field], value)
        else:
            current[field] = copy.deepcopy(value)


def validate_page(page):
    require(isinstance(page, dict), "invalid_baseline", "页面配置无效。")
    integer(page.get("lightness"), 0, 100, "亮度")
    integer(page.get("speed_ms"), 0 if page.get("valid") in (0, False) else 1, 32767, "播放间隔")
    color = page.get("color")
    require(isinstance(color, dict) and all(isinstance(color.get(field), str) and RGB_RE.fullmatch(color[field])
                                          for field in ("back_rgb", "rgb")), "invalid_config", "页面颜色配置无效。")
    words = page.get("word_page")
    require(isinstance(words, dict), "invalid_config", "页面文字配置不完整。")
    length = integer(words.get("word_len"), 0, 255, "文字长度")
    text = words.get("unicode")
    require(isinstance(text, list) and (length == 0 or len(text) == length) and
            all(isinstance(code, str) and UNICODE_RE.fullmatch(code) for code in text),
            "invalid_config", "页面文字长度或编码无效。")
    for field, count in (("frames", 200), ("keyframes", 90)):
        group = page.get(field)
        require(isinstance(group, dict), "invalid_baseline", "页面的动画配置不完整。")
        n = integer(group.get("frame_num"), 0, 255, "帧数")
        if n:
            data = group.get("frame_data")
            require(isinstance(data, list) and len(data) == n,
                    "invalid_animation", "帧数和动画数据不一致。")
            require(all(isinstance(frame, dict) and frame.get("frame_index") == i for i, frame in enumerate(data)),
                    "invalid_animation", "动画帧编号必须从 0 连续排列。")
            validate_animation([frame.get("frame_RGB") for frame in data], count, "顶屏" if count == 200 else "轴灯")


def validate_config(config, cli):
    require(isinstance(config, dict) and isinstance(config.get("page_data"), list),
            "invalid_baseline", "本机配置不是完整的键盘配置。")
    require(config.get("page_num") == len(config["page_data"]),
            "invalid_baseline", "本机配置的页面数不一致。")
    require_supported_write(config)
    indices = [page.get("page_index") for page in config["page_data"]]
    require(len(set(indices)) == len(indices) and all(type(i) is int and 0 <= i <= 255 for i in indices),
            "invalid_baseline", "配置包含无效页面编号。")
    validate_layers(config.get("key_layer"))
    for page in config["page_data"]:
        validate_page(page)
    try:
        fp = cli["cb_write"].plan(config)
    except (KeyError, ValueError, TypeError, OverflowError) as error:
        raise BridgeError("invalid_config", "配置无法转换为键盘可接收的数据。", reason=str(error)) from error
    require(fp.total > 0 and all(len(frame) == 64 and cli["cb_protocol"].crc_ok(frame) for frame in fp.frames),
            "invalid_wire_frames", "配置校验未通过，未进行写入。")
    return fp


def validate_builtin_pages(pages):
    require(isinstance(pages, list) and len(pages) == 5 and
            all(isinstance(page, dict) for page in pages) and
            [page.get("page_index") for page in pages] == list(range(5)),
            "builtin_defaults_invalid", "官网标准内置模式资源缺少完整的页面 0–4。")
    allowed = {"//", "valid", "page_index", "lightness", "speed_ms", "color", "word_page", "frames", "keyframes"}
    required = allowed - {"//"}
    for page in pages:
        require(required <= set(page) <= allowed,
                "builtin_defaults_invalid", "官网标准内置模式资源包含缺失或不支持的页面字段。")
        for field, fields in (("color", {"//", "default", "back_rgb", "rgb"}),
                              ("word_page", {"//", "valid", "word_len", "unicode"}),
                              ("frames", {"//", "valid", "frame_num", "frame_data"}),
                              ("keyframes", {"//", "valid", "frame_num", "frame_data"})):
            group = page.get(field)
            require(isinstance(group, dict) and fields - {"//"} <= set(group) <= fields,
                    "builtin_defaults_invalid", "官网标准内置模式资源包含不完整的页面控制数据。")
        require(not unsafe_wire_flag_paths({"page_data": [page]}),
                "builtin_defaults_invalid", "官网标准内置模式资源的启用标记无效。")
        validate_page(page)
        for field in ("frames", "keyframes"):
            require(isinstance(page[field].get("frame_data"), list),
                    "builtin_defaults_invalid", "官网标准内置模式资源的动画占位数据无效。")
    return pages


def initial_configuration(product_id, live, builtin_pages):
    """Public, explicitly new configuration; never a factory/prior baseline.

    The only device-derived data is the CRC-checked live seven-layer matrix.
    Empty exchange/swap tables are a declared replacement policy. Unsupported
    Fn/macro tables are deliberately absent, rather than invented defaults.
    """
    validate_layers(live)
    pages = copy.deepcopy(validate_builtin_pages(builtin_pages))
    for index in range(5, 8):

        def stream(count):
            return {"valid": 0, "frame_num": 1,
                    "frame_data": [{"frame_index": 0, "frame_RGB": ["#000000"] * count}]}

        pages.append({"valid": False, "page_index": index, "lightness": 0, "speed_ms": 40,
                      "color": {"default": False, "back_rgb": "#000000", "rgb": "#000000"},
                      "word_page": {"valid": 0, "word_len": 0, "unicode": []},
                      "frames": stream(200), "keyframes": stream(90)})
    key_layer = copy.deepcopy(live)
    key_layer["valid"] = 1  # A false flag would silently skip every keymap wire frame.
    return {"product_info": {"product_id": product_id}, "page_num": 8, "page_data": pages,
            "key_layer": key_layer, "exchange_num": 0, "exchange_key": [],
            "swap_key_num": 0, "swap_key": []}


def validate_initial_configuration(target, live, applied_slots, cli, builtin_pages):
    """Enforce the reviewed initialization policy as well as wire validity."""
    require(isinstance(applied_slots, list) and 1 <= len(applied_slots) <= 3 and
            all(type(slot) is int and 1 <= slot <= 3 for slot in applied_slots) and
            len(set(applied_slots)) == len(applied_slots), "plan_tampered", "首次配置槽位计划无效，请重新准备。")
    neutral = initial_configuration(target.get("product_info", {}).get("product_id"), live, builtin_pages)
    unchanged = copy.deepcopy(target)
    require(isinstance(target.get("page_data"), list) and
            [page.get("page_index") for page in target["page_data"]] == list(range(8)),
            "plan_tampered", "首次配置页面计划无效，请重新准备。")
    for slot in applied_slots:
        page, original = page_for(unchanged, slot), page_for(neutral, slot)
        require(page.get("valid") is True and page.get("word_page") == original["word_page"] and
                page.get("color") == original["color"],
                "plan_tampered", "首次配置包含未授权的页面设置。")
        for field in ("frames", "keyframes"):
            require(page.get(field, {}).get("valid") == 1 and page.get(field, {}).get("frame_num", 0) > 0,
                    "plan_tampered", "首次配置缺少已选择的动画。")
        for field in ("valid", "frames", "keyframes", "lightness", "speed_ms"):
            page[field] = copy.deepcopy(original[field])
    require(unchanged == neutral, "plan_tampered", "首次配置包含未授权的键位或模式变化。")
    return validate_config(target, cli)


class Bridge:
    def __init__(self, state_dir, resource_dir, cli=None, cli_version=None, event_sink=emit):
        if cli is None:
            cli, cli_version = load_cli()
        self.cli, self.cli_version = cli, cli_version or "unknown"
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.resource_dir = Path(resource_dir).expanduser().resolve()
        self.event_sink = event_sink

    def event(self, stage, transferred=0, total=0, **extra):
        self.event_sink({"event": "progress", "stage": stage, "transferred": transferred, "total": total, **extra})

    def testAIConnection(self, payload):
        from kimi_ai import AIError, AIClient, configuration
        try:
            client = AIClient(configuration(payload.get("ai")),
                                progress=lambda stage, message: self.event(stage, message=message), timeout=45)
            return client.test_connection()
        except AIError as error:
            raise BridgeError(error.code, error.message) from None

    def generateAI(self, payload):
        from kimi_ai import AIError, generate
        try:
            result = generate(payload, progress=lambda stage, message: self.event(
                stage, message=message, requestId=payload.get("requestId")))
            validate_animation(result["design"]["frames"], 200, "顶屏")
            validate_animation(result["design"]["keyframes"], 90, "轴灯")
            return result
        except AIError as error:
            raise BridgeError(error.code, error.message) from None

    def prepareAIImages(self, payload):
        from ai_images import ImageError, from_paths
        try:
            return from_paths(payload.get("paths"))
        except ImageError as error:
            raise BridgeError("ai_image_invalid", str(error)) from None

    def stored_product(self):
        store = self.cli["cb_store"]
        devices = store.store_root() / "devices"
        if not devices.is_dir():
            return None
        known = [path.name for path in devices.iterdir() if path.is_dir() and recognized(path.name)]
        if "AM01R6" in known:
            return "AM01R6"
        return known[0] if len(known) == 1 else None

    def device_dict(self, identity=None, product_id=None):
        pid = identity.product_id if identity else product_id
        meta = self.cli["cb_store"].load_meta(pid) or {} if pid else {}
        return {"productId": pid, "firmware": identity.version if identity else meta.get("version"),
                "lastSeen": now_iso() if identity else meta.get("last_seen"),
                "port": identity.port if identity else None, "connected": identity is not None}

    def stored_config(self, pid, required=False):
        config = self.cli["cb_store"].load_current(pid) if pid else None
        require(not required or config is not None, "baseline_missing",
                "缺少这把键盘在本机的完整配置记录，不能安全保留未知灯效。请迁移这把键盘此前成功写入的完整记录，"
                "或明确选择应用内首次配置（会替换未知设置）；应用导入只导入灯效。")
        if config:
            config = copy.deepcopy(config)
            config.pop("_provenance", None)
        return config

    def require_current_led_baseline(self, pid, current):
        """Do not reuse an old unreadable LED baseline after a consumed write.

        Plan metadata and its result are independent local completion records.
        Either can establish verified success; an executing record alone cannot.
        A trusted CLI update to current resolves the old-baseline uncertainty.
        """
        directory = self.state_dir / "plans"
        if not directory.is_dir():
            return
        candidates = []
        for folder in directory.iterdir():
            try:
                metadata = load_json(folder / "plan.json")
                if not isinstance(metadata, dict) or metadata.get("productId") != pid or \
                        metadata.get("planVersion") != 2 or metadata.get("token") != folder.name or \
                        metadata.get("status") not in ("executing", "complete"):
                    continue
                if not all(isinstance(metadata.get(field), str) and
                           re.fullmatch(r"[0-9a-f]{64}", metadata[field])
                           for field in ("storedBaselineHash", "targetHash")):
                    continue
                try:
                    report = load_json(folder / "result.json")
                except (OSError, ValueError, TypeError):
                    report = {}
                if not isinstance(report, dict):
                    report = {}
                readback_attempts = report.get("readbackAttempts", [])
                if not isinstance(readback_attempts, list):
                    readback_attempts = []
                verified_metadata = metadata.get("status") == "complete" and \
                    metadata.get("deviceAck") is True and metadata.get("keymapMatch") is True and \
                    metadata.get("verifiedTargetHash") == metadata["targetHash"]
                verified_report = report.get("success") is True and report.get("deviceAck") is True and \
                    report.get("keymapMatch") is True and \
                    report.get("verifiedTargetHash", metadata["targetHash"]) == metadata["targetHash"] and \
                    any(isinstance(attempt, dict) and attempt.get("keymapMatch") is True and
                        attempt.get("completeKeycodes") == 1400 for attempt in readback_attempts)
                stamps = [metadata.get("createdTimestamp"), metadata.get("startedTimestamp"),
                          metadata.get("completedTimestamp")]
                if verified_report:
                    stamps.append(report.get("completedTimestamp"))
                stamp = max((value for value in stamps if type(value) in (int, float) and math.isfinite(value)), default=0)
                candidates.append((stamp, folder.name, metadata, verified_metadata or verified_report))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        if not candidates:
            return
        _, _, latest, verified = max(candidates, key=lambda value: value[:2])
        current_hash = digest(current)
        if current_hash != latest["storedBaselineHash"] or current_hash == latest["targetHash"]:
            return
        previous_mtime = latest.get("currentRecordMtimeNs")
        current_mtime = self.current_record_mtime_ns(pid)
        if type(previous_mtime) is int and previous_mtime > 0 and \
                type(current_mtime) is int and current_mtime != previous_mtime:
            # The CLI current file is the existing trusted configuration input.
            # A later rewrite can intentionally restore the same old content;
            # a changed file fingerprint permits it without claiming that an
            # unknown device write became verified or inferring elapsed time.
            return
        if verified:
            raise BridgeError("baseline_store_incomplete",
                              "上次灯效已同步，但本机完整配置记录仍是同步前的旧版本。继续同步可能覆盖刚成功的灯效。"
                              "请先通过可信 CLI 修复或更新完整配置记录，再重新准备同步。")
        raise BridgeError("baseline_result_unknown",
                          "上次设备写入的结果未能完整留存，当前灯效基线无法确认。"
                          "请先通过可信 CLI 更新完整配置记录，再重新准备同步。")

    def current_record_mtime_ns(self, pid):
        try:
            return self.cli["cb_store"].current_path(pid).stat().st_mtime_ns
        except (OSError, AttributeError, TypeError, ValueError):
            return None

    def provenance(self, config, key_source="stored"):
        if config is None:
            return None
        out = copy.deepcopy(config)
        out["_provenance"] = {"led": "last-written", "keymap": key_source}
        return out

    def bootstrap(self, payload):
        pid = self.stored_product()
        config = self.stored_config(pid)
        workspace, workspace_warning = self.load_workspace()
        result = {"device": self.device_dict(product_id=pid), "config": self.provenance(config),
                "history": self.history_items(pid), "cliVersion": self.cli_version,
                "ledSource": "last-written" if config else "unknown", "workspace": workspace}
        result["keymap"] = None
        if config and isinstance(config.get("key_layer"), dict):
            try:
                validate_layers(config["key_layer"])
                result["keymap"] = self.keymap_view(config["key_layer"], source="cached")
            except BridgeError:
                # Old/malformed records remain available under the existing
                # config policy; do not present an incomplete editable matrix.
                pass
        if workspace_warning:
            result["workspaceWarning"] = workspace_warning
        return result

    def validate_workspace(self, payload):
        require(isinstance(payload, dict), "invalid_workspace", "工作台草稿格式无效。")
        designs, pending = payload.get("designs", []), payload.get("pending", [])
        trash = payload.get("trash", [])
        require(isinstance(designs, list) and len(designs) <= 30,
                "workspace_limit", "最多保存 30 套自定义灯效。请导出后清理不需要的作品。")
        require(isinstance(trash, list) and len(trash) <= 30,
                "workspace_limit", "回收站最多保存 30 套作品。请恢复或明确删除部分作品后再试。")

        def text_fits(value, maximum):
            # Match JavaScript string.length so emoji cannot cross the shared
            # frontend/backend metadata limits unnoticed.
            return isinstance(value, str) and len(value.encode("utf-16-le", errors="surrogatepass")) // 2 <= maximum

        removed_builtins = payload.get("removedBuiltinIds", [])
        require(isinstance(removed_builtins, list) and len(removed_builtins) <= 255,
                "invalid_workspace", "已移除的内置作品清单无效。")
        require(all(text_fits(identity, 256) and identity.strip() and
                    not re.search(r"[\x00-\x1F\x7F]", identity) for identity in removed_builtins) and
                len(set(removed_builtins)) == len(removed_builtins),
                "invalid_workspace", "已移除的内置作品编号缺失、重复或无效。")

        def validate_design(design, identities):
            require(isinstance(design, dict), "invalid_workspace", "工作台作品格式无效。")
            identity = design.get("id")
            require(isinstance(identity, str) and 0 < len(identity) <= 256 and identity not in identities,
                    "invalid_workspace", "工作台作品编号缺失或重复。")
            identities.add(identity)
            require(isinstance(design.get("name"), str) and 0 < len(design["name"]) <= 256,
                    "invalid_workspace", "工作台作品名称无效。")
            require(identity.strip() and design["name"].strip() and
                    text_fits(identity, 256) and text_fits(design["name"], 256) and
                    not re.search(r"[\x00-\x1F\x7F]", identity + design["name"]),
                    "invalid_workspace", "作品编号与名称不能为空白或包含控制字符。")
            validate_animation(design.get("frames"), 200, "顶屏")
            validate_animation(design.get("keyframes"), 90, "轴灯")
            integer(design.get("speed_ms"), 1, 32767, "播放间隔")
            if "description" in design:
                require(text_fits(design["description"], 32768),
                        "invalid_workspace", "作品描述必须是 32768 字以内的文字。")
            if "palette" in design:
                require(isinstance(design["palette"], list) and len(design["palette"]) <= 16 and
                        all(isinstance(color, str) and RGB_RE.fullmatch(color) for color in design["palette"]),
                        "invalid_workspace", "作品代表色必须为最多 16 个 #RRGGBB 颜色。")
            if "preview_brightness" in design:
                integer(design["preview_brightness"], 0, 100, "作品预览亮度")
            if "frame_count" in design:
                require(type(design["frame_count"]) is int and design["frame_count"] == len(design["frames"]),
                        "invalid_workspace", "作品帧数必须与顶部动画一致。")
            if "stages" in design:
                stages = design["stages"]
                require(isinstance(stages, list) and len(stages) <= 255,
                        "invalid_workspace", "作品阶段必须为最多 255 项的列表。")
                strings = all(text_fits(stage, 256) for stage in stages)
                ranges = all(isinstance(stage, dict) and set(stage) == {"name", "end"} and text_fits(stage.get("name"), 256) and
                             type(stage.get("end")) is int and
                             1 <= stage["end"] <= len(design["frames"]) for stage in stages)
                require(strings or ranges, "invalid_workspace", "作品阶段必须全部为名称或合法的阶段范围。")
                if stages and ranges:
                    require(all(left["end"] < right["end"] for left, right in zip(stages, stages[1:])),
                            "invalid_workspace", "作品阶段范围必须按结束帧递增。")

        ids, trash_ids = set(), set()
        for design in designs:
            validate_design(design, ids)
        for entry in trash:
            require(isinstance(entry, dict) and set(entry) == {"design", "deletedAt"},
                    "invalid_workspace", "回收站记录格式无效。")
            validate_design(entry.get("design"), trash_ids)
            deleted_at = entry.get("deletedAt")
            require(isinstance(deleted_at, str) and len(deleted_at) <= 64 and
                    re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", deleted_at),
                    "invalid_workspace", "回收站移入时间必须为带时区的 ISO 日期。")
            try:
                parsed = datetime.fromisoformat(deleted_at.replace("Z", "+00:00"))
                require(parsed.tzinfo is not None, "invalid_workspace", "回收站移入时间无效。")
            except ValueError:
                raise BridgeError("invalid_workspace", "回收站移入时间无效。") from None
        require(isinstance(pending, list) and len(pending) <= 3,
                "invalid_workspace", "工作台最多保留 3 个槽位草稿。")
        slots = set()
        for item in pending:
            require(isinstance(item, dict), "invalid_workspace", "槽位草稿格式无效。")
            slot = integer(item.get("slot"), 1, 3, "自定义槽")
            require(slot not in slots, "invalid_workspace", "槽位草稿不能重复。")
            slots.add(slot)
            require(isinstance(item.get("designId"), str) and 0 < len(item["designId"]) <= 256,
                    "invalid_workspace", "槽位草稿缺少作品编号。")
            # A re-imported active work may reuse an archived ID. Drafts resolve
            # against active works first; an archive-only work cannot be assigned.
            require(item["designId"] not in trash_ids or item["designId"] in ids,
                    "invalid_workspace", "槽位草稿不能引用回收站中的作品，请先恢复该作品。")
            require(item["designId"] not in removed_builtins or item["designId"] in ids,
                    "invalid_workspace", "槽位草稿不能引用已移除的内置作品，请先恢复该作品。")
            # Built-in library IDs need not appear in custom designs. The UI
            # resolves them against the bundled library when restoring drafts.
            integer(item.get("brightness"), 0, 100, "亮度")
            integer(item.get("speedMs"), 1, 32767, "播放间隔")
        selected = payload.get("selectedId")
        require(selected is None or isinstance(selected, str) and 0 < len(selected) <= 256,
                "invalid_workspace", "选中的作品编号无效。")
        target = integer(payload.get("targetSlot", 1), 1, 3, "自定义槽")
        brightness = integer(payload.get("brightness", 100), 0, 100, "亮度")
        speed_ms = integer(payload.get("speedMs", 40), 1, 32767, "播放间隔")
        export_format = payload.get("exportFormat", "design")
        require(export_format in ("design", "config"), "invalid_workspace", "导出格式无效。")
        brief = payload.get("brief", "")
        require(isinstance(brief, str) and len(brief) <= 20000,
                "invalid_workspace", "创作描述需要在 20000 字以内。")
        palette = payload.get("palette", "original")
        require(isinstance(palette, str) and len(palette) <= 128 or
                isinstance(palette, list) and len(palette) <= 16 and
                all(isinstance(color, str) and RGB_RE.fullmatch(color) for color in palette),
                "invalid_workspace", "工作台配色格式无效。")
        workspace = {"designs": copy.deepcopy(designs), "trash": copy.deepcopy(trash), "pending": copy.deepcopy(pending),
                     "removedBuiltinIds": copy.deepcopy(removed_builtins),
                     "selectedId": selected, "targetSlot": target, "brief": brief, "palette": copy.deepcopy(palette),
                     "brightness": brightness, "speedMs": speed_ms, "exportFormat": export_format}
        ui_theme = payload.get("uiTheme", "dark")
        require(isinstance(ui_theme, str) and ui_theme in ("dark", "island"),
                "invalid_workspace", "界面风格无效。")
        workspace["uiTheme"] = ui_theme
        conversations = copy.deepcopy(payload.get("conversations", []))
        require(isinstance(conversations, list) and len(conversations) <= 20,
                "workspace_limit", "最多保留 20 个创作会话，请导出作品并整理会话。")
        conversation_ids = set()
        for conversation in conversations:
            require(isinstance(conversation, dict) and set(conversation) <= {
                "id", "title", "createdAt", "updatedAt", "draft", "turns", "versions", "selectedVersionId"},
                "invalid_workspace", "创作会话字段无效。")
            identity = conversation.get("id")
            require(text_fits(identity, 128) and identity.strip() and identity not in conversation_ids,
                    "invalid_workspace", "创作会话编号缺失或重复。")
            conversation_ids.add(identity)
            require(text_fits(conversation.get("title"), 256), "invalid_workspace", "会话名称过长。")
            for timestamp in ("createdAt", "updatedAt"):
                require(text_fits(conversation.get(timestamp), 64), "invalid_workspace", "会话时间无效。")
            versions = conversation.get("versions", [])
            require(isinstance(versions, list) and len(versions) <= 12,
                    "workspace_limit", "每个会话最多保留 12 个版本，请保存作品后开启新会话。")
            version_ids = set()
            for version in versions:
                require(isinstance(version, dict) and set(version) <= {
                    "id", "label", "createdAt", "design", "provider", "model", "savedDesignId", "baseVersionId", "scope", "changeSummary"},
                    "invalid_workspace", "创作版本字段无效。")
                version_id = version.get("id")
                require(text_fits(version_id, 128) and version_id.strip() and version_id not in version_ids,
                        "invalid_workspace", "创作版本编号缺失或重复。")
                version_ids.add(version_id)
                validate_design(version.get("design"), set())
                require(version.get("baseVersionId") is None or
                        version["baseVersionId"] in version_ids and version["baseVersionId"] != version_id,
                        "invalid_workspace", "创作版本的基础版本不存在。")
                require(text_fits(version.get("label", ""), 256) and text_fits(version.get("createdAt", ""), 64),
                        "invalid_workspace", "创作版本说明无效。")
                for field in ("provider", "model", "savedDesignId", "baseVersionId"):
                    require(version.get(field) is None or text_fits(version[field], 256),
                            "invalid_workspace", "创作版本来源无效。")
                require(version.get("scope", "both") in ("both", "top", "keys"),
                        "invalid_workspace", "版本修改范围无效。")
                require(text_fits(version.get("changeSummary", ""), 2000),
                        "invalid_workspace", "版本修改说明过长。")
            selected_version = conversation.get("selectedVersionId")
            require(selected_version is None or selected_version in version_ids,
                    "invalid_workspace", "选中的创作版本不存在。")

            def validate_conversation_images(images):
                from ai_images import from_payload, ImageError
                require(isinstance(images, list) and len(images) <= 3,
                        "invalid_workspace", "每条创作记录最多保留三张参考图。")
                for image in images:
                    require(isinstance(image, dict) and set(image) <= {"name", "dataUrl"} and
                            text_fits(image.get("name", "参考图"), 256),
                            "invalid_workspace", "会话参考图字段无效。")
                if images:
                    try:
                        normalized = from_payload(images)
                        images[:] = [{"name": image["name"], "dataUrl": image["dataUrl"]} for image in normalized]
                    except ImageError:
                        raise BridgeError("invalid_workspace", "会话参考图格式或大小无效。") from None

            draft = conversation.get("draft", {})
            require(isinstance(draft, dict) and set(draft) <= {"brief", "images", "scope", "baseVersionId"},
                    "invalid_workspace", "会话输入草稿字段无效。")
            require(text_fits(draft.get("brief", ""), 4000) and draft.get("scope", "both") in ("both", "top", "keys"),
                    "invalid_workspace", "会话输入或修改范围无效。")
            require(draft.get("baseVersionId") is None or draft["baseVersionId"] in version_ids,
                    "invalid_workspace", "会话修改基底不存在。")
            validate_conversation_images(draft.get("images", []))
            turns = conversation.get("turns", [])
            require(isinstance(turns, list) and len(turns) <= 60,
                    "workspace_limit", "会话记录已达上限，请保存作品后开启新会话。")
            turn_ids = set()
            for turn in turns:
                require(isinstance(turn, dict) and set(turn) <= {
                    "id", "role", "text", "createdAt", "versionId", "status", "images", "requestId", "baseVersionId", "provider", "model", "scope"},
                    "invalid_workspace", "对话记录字段无效。")
                turn_id = turn.get("id")
                require(text_fits(turn_id, 128) and turn_id.strip() and turn_id not in turn_ids,
                        "invalid_workspace", "对话记录编号无效。")
                turn_ids.add(turn_id)
                require(turn.get("role") in ("user", "assistant") and text_fits(turn.get("text", ""), 6000),
                        "invalid_workspace", "对话角色或内容无效。")
                require(text_fits(turn.get("createdAt", ""), 64), "invalid_workspace", "对话时间无效。")
                require(turn.get("versionId") is None or turn["versionId"] in version_ids,
                        "invalid_workspace", "对话引用版本不存在。")
                require(turn.get("baseVersionId") is None or turn["baseVersionId"] in version_ids,
                        "invalid_workspace", "对话引用的基础版本不存在。")
                require(turn.get("scope", "both") in ("both", "top", "keys"),
                        "invalid_workspace", "对话修改范围无效。")
                for field in ("status", "requestId", "baseVersionId", "provider", "model", "scope"):
                    require(turn.get(field) is None or text_fits(turn[field], 256),
                            "invalid_workspace", "对话状态无效。")
                validate_conversation_images(turn.get("images", []))
        active_conversation = payload.get("activeConversationId")
        require(active_conversation is None or active_conversation in conversation_ids,
                "invalid_workspace", "当前创作会话不存在。")
        workspace["conversations"] = copy.deepcopy(conversations)
        workspace["activeConversationId"] = active_conversation
        if "keymapDraft" in payload:
            workspace["keymapDraft"] = self.validate_keymap_draft(payload["keymapDraft"])
        def has_credential(value):
            if isinstance(value, dict):
                return any(str(key).lower() in ("apikey", "api_key", "authorization", "credential", "password") or
                           has_credential(item) for key, item in value.items())
            if isinstance(value, list):
                return any(has_credential(item) for item in value)
            return isinstance(value, str) and bool(re.search(r"\bsk-(?:cp-)?[A-Za-z0-9_-]{20,}", value))
        require(not has_credential(workspace), "workspace_credentials", "作品或对话中包含密钥，请移除密钥后保存。")
        if "previewAppearanceId" in payload:
            appearance = payload["previewAppearanceId"]
            require(isinstance(appearance, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", appearance),
                    "invalid_workspace", "预览外观编号无效。")
            workspace["previewAppearanceId"] = appearance
        try:
            encoded = json.dumps(workspace, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as error:
            raise BridgeError("invalid_workspace", "工作台数据无法保存为 JSON。") from error
        require(len(encoded) <= MAX_WORKSPACE_BYTES - 256, "workspace_too_large",
                "工作台草稿超过 32 MB，请导出并清理部分作品。")
        return workspace

    def load_workspace(self):
        location = self.state_dir / "workspace.json"
        if not location.is_file():
            return None, None
        try:
            require(location.stat().st_size <= MAX_WORKSPACE_BYTES, "workspace_too_large", "工作台草稿超过 32 MB。")
            saved = load_json(location)
            require(isinstance(saved, dict) and type(saved.get("version", 1)) is int and
                    saved.get("version", 1) in (1, 2), "invalid_workspace", "工作区版本无效或暂不支持。")
            workspace = self.validate_workspace(saved)
            workspace["savedAt"] = saved.get("savedAt")
            return workspace, None
        except (BridgeError, OSError, ValueError, TypeError, KeyError):
            return None, "保存的工作台草稿无法载入。原文件已保留，灯效与设备配置不受影响。"

    def preserve_unreadable_workspace(self, source):
        """Preserve every original byte before recovering an unreadable store.

        Stream even an oversized damaged file; never decode/log its potentially
        private contents or overwrite a previous recovery snapshot.
        """
        import os
        temporary = source.with_name(f".workspace-recovery.{uuid.uuid4().hex}.tmp")
        digest = hashlib.sha256()
        try:
            with source.open("rb") as original, temporary.open("xb") as snapshot:
                while data := original.read(1024 * 1024):
                    digest.update(data)
                    snapshot.write(data)
                snapshot.flush()
                os.fsync(snapshot.fileno())
            temporary.chmod(0o600)
            backup = source.with_name("workspace-recovery-" + digest.hexdigest() + ".json")
            if backup.exists():
                # Repeated failed saves reuse an intact snapshot; a conflicting
                # manually edited snapshot is retained under its old name.
                existing = hashlib.sha256()
                with backup.open("rb") as previous:
                    while data := previous.read(1024 * 1024):
                        existing.update(data)
                if existing.digest() == digest.digest():
                    return backup
                backup = source.with_name("workspace-recovery-" + digest.hexdigest() + "-" + uuid.uuid4().hex + ".json")
            temporary.replace(backup)
            return backup
        except OSError:
            raise BridgeError("workspace_recovery_failed", "无法备份原工作区，已停止保存以保留原文件。请检查本机存储后重试。") from None
        finally:
            temporary.unlink(missing_ok=True)

    def saveWorkspace(self, payload):
        workspace = self.validate_workspace(payload)
        workspace.update(version=2, savedAt=now_iso())
        # One pre-conversation snapshot supports an explicit return to the prior
        # release. It stays in the private data directory, never in the bundle.
        previous = self.state_dir / "workspace.json"
        backup = self.state_dir / "workspace-before-1.0.json"
        if previous.is_file():
            try:
                require(previous.stat().st_size <= MAX_WORKSPACE_BYTES, "workspace_too_large", "旧工作区过大。")
                old = load_json(previous)
                require(isinstance(old, dict) and type(old.get("version", 1)) is int and
                        old.get("version", 1) in (1, 2), "invalid_workspace", "旧工作区版本无效。")
                self.validate_workspace(old)
            except (BridgeError, OSError, ValueError, TypeError, KeyError):
                self.preserve_unreadable_workspace(previous)
            else:
                if old.get("version", 1) < 2 and not backup.exists():
                    atomic_json(backup, old, compact=True)
        atomic_json(self.state_dir / "workspace.json", workspace, compact=True)
        return {"saved": True, "savedAt": workspace["savedAt"], "designCount": len(workspace["designs"]),
                "pendingCount": len(workspace["pending"]), "trashCount": len(workspace["trash"])}

    def discover(self, payload=None):
        payload = payload or {}
        named = payload.get("port")
        device = self.cli["cb_device"]
        ports = device.candidate_ports()
        require(not named or named in ports, "invalid_port", "所选 USB 设备已断开，请重新检测。")
        identities = []
        failures = []
        identity_query_failed = False
        unknown_query_failed = False
        diagnostic_probe = getattr(device, "probe_with_diagnostics", None)
        for port in ([named] if named else ports):
            failure = None
            try:
                if callable(diagnostic_probe):
                    info, failure = diagnostic_probe(port, full=True)
                    if failure:
                        failures.append(failure)
                else:
                    # Older macOS CLI runtimes lack the optional diagnostics
                    # API. Continue scanning after their I/O failures, but do
                    # not assume an exception happened before identity was
                    # verified: it could conceal a second connected keyboard.
                    info = device.probe(port, full=True)
            except OSError as error:
                unknown_query_failed = True
                failures.append({"port": port, "stage": "unknown",
                                 "kind": "timeout" if "timeout" in str(error).lower() else "serial_error",
                                 "reason": str(error)[:500]})
                continue
            if info is not None and recognized(info.product_id) and not info.is_dongle:
                identities.append(info)
                if failure:
                    identity_query_failed = True
        require(len(identities) <= 1, "ambiguous_device", "检测到多把键盘，请只连接需要同步的一把。")
        if failures and (not identities or identity_query_failed or unknown_query_failed):
            failed_ports = list(dict.fromkeys(str(item.get("port", "?")) for item in failures))
            stage_names = {"open": "打开端口", "identity": "设备识别", "firmware": "固件信息查询", "pages": "槽位信息查询"}
            failed_checks = list(dict.fromkeys(
                f"{item.get('port', '?')}（{stage_names.get(item.get('stage'), '通信检测')}）" for item in failures))
            label = "、".join(failed_checks[:8])
            timed_out = any(item.get("kind") == "timeout" for item in failures)
            issue = "通信超时" if timed_out else "无法完成通信"
            raise BridgeError("serial_probe_failed",
                              f"USB 串口 {label} {issue}，尚未确认键盘连接。请关闭 AM_Master 等配置软件，重插 USB 数据线后再检查。",
                              stage="discovery", probeFailures=failures[:16], ports=failed_ports)
        return identities[0] if identities else None

    def read_live(self, port):
        try:
            frames = self.cli["cb_read"]._drain(port, (6, 9), timeout=1.5)
        except OSError as error:
            timed_out = "timeout" in str(error).lower()
            issue = "通信超时" if timed_out else "通信失败"
            raise BridgeError("serial_keymap_failed",
                              f"{port} 键位查询{issue}。请关闭其他键盘配置软件，重新连接后再检查。",
                              port=port, stage="keymap", kind="timeout" if timed_out else "serial_error",
                              reason=str(error)[:500]) from error
        require(len(frames) == 94 and all(len(frame) == 64 and frame[:2] == b"\x06\x09" and
                                        self.cli["cb_protocol"].crc_ok(frame) for frame in frames),
                "incomplete_keymap", "USB 键位读取不完整，请重新连接后检测。")
        require(sorted(frame[2] for frame in frames) == list(range(94)),
                "incomplete_keymap", "USB 键位读取缺少数据，请重试。")
        frames.sort(key=lambda frame: frame[2])
        blob = b"".join(frame[3:63] for frame in frames)[:5600]
        codes = ["#" + blob[index:index + 4].hex().upper() for index in range(0, 5600, 4)]
        fragment = {"valid": 1, "layer_num": 7,
                    "layer_data": [{"layer": codes[index:index + 200]} for index in range(0, 1400, 200)]}
        validate_layers(fragment)
        return fragment, b"".join(frames)

    def layout(self):
        location = self.resource_dir / "web" / "assets" / "keymap-layout.json"
        require(location.is_file(), "layout_missing", "应用缺少实体键盘布局资源。")
        data = load_json(location)
        keys = data.get("keys") if isinstance(data, dict) else data
        require(isinstance(keys, list) and len(keys) == 81, "layout_invalid", "实体键盘布局资源无效。")
        require(len({key.get("matrix_index") for key in keys}) == 81 and
                all(type(key.get("matrix_index")) is int and 0 <= key["matrix_index"] < 200 for key in keys),
                "layout_invalid", "实体键盘布局资源无效。")
        return keys

    def keymapCatalog(self, payload):
        return keymap_codec.catalog()

    def decode_binding(self, code, known=None):
        return keymap_codec.decode(code)

    def keymap_view(self, live, *, source="live"):
        keys = copy.deepcopy(self.layout())
        for key in keys:
            key["bindings"] = [self.decode_binding(layer["layer"][key["matrix_index"]])
                               for layer in live["layer_data"]]
        return {**copy.deepcopy(live), "keys": keys, "source": source, "physicalKeyCount": 81,
                "keymapHash": hashlib.sha256(matrix(live)).hexdigest()}

    def detect(self, payload):
        identity = self.discover(payload)
        if identity is None:
            out = self.bootstrap({})
            return {**out, "connected": False}
        live, _ = self.read_live(identity.port)
        config = self.stored_config(identity.product_id)
        if config:
            config["key_layer"] = live
        self.state_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(self.state_dir / "last-device.json", self.device_dict(identity))
        return {"connected": True, "device": self.device_dict(identity), "keymap": self.keymap_view(live),
                "config": self.provenance(config, "live"), "ledSource": "last-written" if config else "unknown"}

    def keymap(self, payload):
        return self.detect(payload)

    def validated_key_changes(self, changes, *, allow_empty=False, error_code="invalid_key_change"):
        require(isinstance(changes, list) and (allow_empty or bool(changes)) and len(changes) <= 81 * 7,
                error_code, "请选择需要修改的实体键位。")
        allowed = {key["matrix_index"] for key in self.layout()}
        seen = set()
        for change in changes:
            require(isinstance(change, dict) and set(change) == {"layer", "matrixIndex", "code"},
                    error_code, "键位修改字段无效。")
            layer, index, code = change.get("layer"), change.get("matrixIndex"), change.get("code")
            require(type(layer) is int and 0 <= layer <= 6 and type(index) is int and index in allowed and
                    isinstance(code, str) and KEY_RE.fullmatch(code), error_code,
                    "只能修改实体键的七层绑定，键码需要使用 #MMPPUUUU 格式。")
            pair = (layer, index)
            require(pair not in seen, error_code, "同一层的同一键位不能重复设置。")
            seen.add(pair)
        return copy.deepcopy(changes)

    def validate_keymap_draft(self, draft):
        if draft is None:
            return None
        require(isinstance(draft, dict) and set(draft) == {
            "schemaVersion", "baseHash", "device", "base", "changes", "updatedAt"} and
            type(draft.get("schemaVersion")) is int and draft["schemaVersion"] == 1,
            "invalid_workspace", "键位草稿格式无效。")
        device = draft.get("device")
        require(isinstance(device, dict) and set(device) == {"productId", "firmware"} and
                all(isinstance(device.get(field), str) and 0 < len(device[field]) <= 128 and
                    device[field].strip() and not re.search(r"[\x00-\x1F\x7F]", device[field])
                    for field in ("productId", "firmware")), "invalid_workspace", "键位草稿缺少设备身份。")
        base = draft.get("base")
        require(isinstance(base, list) and len(base) == 7 and all(isinstance(layer, list) for layer in base),
                "invalid_workspace", "键位草稿需要完整的七层基底。")
        fragment = {"layer_num": 7, "layer_data": [{"layer": layer} for layer in base]}
        try:
            baseline_hash = hashlib.sha256(matrix(fragment)).hexdigest()
        except BridgeError:
            raise BridgeError("invalid_workspace", "键位草稿基底不完整。") from None
        require(draft.get("baseHash") == baseline_hash, "invalid_workspace", "键位草稿基底校验失败。")
        self.validated_key_changes(draft.get("changes"), allow_empty=True, error_code="invalid_workspace")
        stamp = draft.get("updatedAt")
        require(isinstance(stamp, str) and len(stamp) <= 64 and
                re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", stamp),
                "invalid_workspace", "键位草稿时间无效。")
        try:
            require(datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo is not None,
                    "invalid_workspace", "键位草稿时间无效。")
        except ValueError:
            raise BridgeError("invalid_workspace", "键位草稿时间无效。") from None
        # Preserve original raw strings/case. Labels are presentation only.
        return copy.deepcopy(draft)

    def keymap_change_summary(self, before, target):
        validate_layers(before["key_layer"])
        validate_layers(target["key_layer"])
        physical = {key["matrix_index"]: key for key in self.layout()}
        changes = []
        for layer, (old_layer, new_layer) in enumerate(zip(before["key_layer"]["layer_data"], target["key_layer"]["layer_data"])):
            for index, (old, new) in enumerate(zip(old_layer["layer"], new_layer["layer"])):
                if old.upper() == new.upper():
                    continue
                require(index in physical, "plan_tampered", "键位计划只能修改实体键。")
                key = physical[index]
                changes.append({"layer": layer, "matrixIndex": index, "physical": key["physical"],
                                "physicalName": key.get("physical_name", key["physical"]),
                                "before": self.decode_binding(old), "after": self.decode_binding(new)})
        return changes

    def keymapPlan(self, payload):
        require(isinstance(payload, dict) and set(payload) <= {
            "expectedKeymapHash", "expectedProductId", "expectedFirmware", "keyChanges", "port"},
            "invalid_keymap_plan", "键位计划不能混入灯效、历史恢复或其他配置修改。")
        expected_hash = payload.get("expectedKeymapHash")
        require(isinstance(expected_hash, str) and re.fullmatch(r"[a-f0-9]{64}", expected_hash),
                "keymap_snapshot_required", "请先读取完整键位，再编辑并准备计划。")
        require(all(isinstance(payload.get(field), str) and 0 < len(payload[field]) <= 128 and
                    payload[field].strip() and not re.search(r"[\x00-\x1F\x7F]", payload[field])
                    for field in ("expectedProductId", "expectedFirmware")),
                "keymap_snapshot_required", "键位草稿缺少读取时的设备身份，请重新读取。")
        changes = self.validated_key_changes(payload.get("keyChanges"))
        identity = self.discover(payload)
        require(identity is not None, "device_missing", "请通过 USB 连接键盘后准备键位计划。")
        require(identity.product_id == payload["expectedProductId"] and identity.version == payload["expectedFirmware"],
                "device_changed", "键位草稿对应的键盘或固件已变化，请重新读取并核对草稿。")
        stored = self.stored_config(identity.product_id, required=True)
        validate_config(stored, self.cli)
        self.require_current_led_baseline(identity.product_id, stored)
        live, raw = self.read_live(identity.port)
        require(hashlib.sha256(matrix(live)).hexdigest() == expected_hash,
                "keymap_changed", "当前键位与草稿基底不同，未刷新或写入键盘；请重新读取并核对修改。")
        changes = [change for change in changes if
                   live["layer_data"][change["layer"]]["layer"][change["matrixIndex"]].upper() != change["code"].upper()]
        require(changes, "empty_keymap_plan", "键位草稿没有实际变化。")
        result = self.prepare({"keyChanges": changes}, (identity, stored, live, raw))
        folder = self.state_dir / "plans" / result["token"]
        before, target = load_json(folder / "before.json"), load_json(folder / "target.json")
        summary = self.keymap_change_summary(before, target)
        metadata = load_json(folder / "plan.json")
        metadata.update(kind="keymap", keyChanges=summary, expectedKeymapHash=expected_hash)
        atomic_json(folder / "plan.json", metadata)
        return {**result, "kind": "keymap", "keyChanges": summary,
                "expectedKeymapHash": expected_hash, "keymapHash": expected_hash,
                "targetKeymap": self.keymap_view(target["key_layer"], source="prepared")}

    def built_in_defaults(self):
        path = self.resource_dir / "web" / "assets" / "builtin-default-pages.json"
        require(path.is_file(), "builtin_defaults_missing", "应用缺少官网标准内置模式资源，请安装完整版本。")
        require(path.stat().st_size <= 1024 * 1024, "builtin_defaults_invalid", "官网标准内置模式资源过大。")
        try:
            data = load_json(path)
        except (OSError, ValueError, TypeError) as error:
            raise BridgeError("builtin_defaults_invalid", "官网标准内置模式资源无法读取。") from error
        require(isinstance(data, dict) and data.get("kind") == "cyberboard-standard-builtin-pages" and
                data.get("schema_version") == 1 and isinstance(data.get("source"), dict),
                "builtin_defaults_invalid", "官网标准内置模式资源格式无效。")
        source = data["source"]
        require(isinstance(source.get("url"), str) and source["url"].startswith("https://diy.angrymiao.com/") and
                isinstance(source.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", source["sha256"]) and
                source.get("pages_sha256") == digest(data.get("pages")),
                "builtin_defaults_invalid", "官网标准内置模式资源来源或页面校验无效。")
        validate_builtin_pages(data.get("pages"))
        return copy.deepcopy(data)

    def builtin_summary(self, config, indices=None):
        indices = range(5) if indices is None else indices
        return [{"pageIndex": index, "name": BUILTIN_NAMES[index], "enabled": nonzero(page_at(config, index).get("valid")),
                 "brightness": page_at(config, index).get("lightness"), "speedMs": page_at(config, index).get("speed_ms")}
                for index in indices]

    def readConfiguration(self, payload):
        identity = self.discover(payload)
        require(identity is not None, "device_missing", "请通过 USB 连接键盘后重新检测。")
        live, _ = self.read_live(identity.port)
        stored = self.stored_config(identity.product_id)
        if stored is None:
            return {"sourceHash": None, "config": None, "device": self.device_dict(identity),
                    "keymap": self.keymap_view(live), "builtInModes": [], "canWrite": False, "unsupportedPaths": [],
                    "configurationSource": "none", "ledSource": "unknown"}
        config = copy.deepcopy(stored)
        # Keep all non-matrix JSON fields; this overlay is a device read only
        # for the complete 1400 keycodes, never for LED pixels or other tables.
        config["key_layer"]["valid"] = 1
        for index, layer in enumerate(live["layer_data"]):
            config["key_layer"]["layer_data"][index]["layer"] = copy.deepcopy(layer["layer"])
        paths, write_error = unsupported_write_paths(config), None
        try:
            validate_config(stored, self.cli)
            self.require_current_led_baseline(identity.product_id, stored)
            validate_config(config, self.cli)
        except (BridgeError, OSError, ValueError, TypeError, KeyError) as error:
            write_error = error
            if isinstance(error, BridgeError):
                paths = sorted(set(paths + error.details.get("unsupportedPaths", [])))
        result = {"sourceHash": digest(stored), "config": self.provenance(config, "live"),
                  "device": self.device_dict(identity), "keymap": self.keymap_view(live),
                  "builtInModes": self.builtin_summary(config), "canWrite": write_error is None,
                  "unsupportedPaths": paths, "configurationSource": "local-last-written-json+live-keymap",
                  "ledSource": "last-written"}
        if write_error is not None:
            result["writeError"] = {"code": write_error.code if isinstance(write_error, BridgeError) else "invalid_config",
                                    "message": str(write_error)}
        return result

    def history_items(self, pid):
        if not pid:
            return []
        sources = [("cli", path) for path in self.cli["cb_store"].list_history(pid)]
        directory = self.state_dir / "backups"
        if directory.is_dir():
            sources.extend(("app", path) for path in directory.glob("*.json") if SNAPSHOT_RE.fullmatch(path.name))
        results = []
        for source, path in sources:
            try:
                config = load_json(path)
                if config.get("_studio_product_id", pid) != pid:
                    continue
                stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
                slots = []
                for slot in (1, 2, 3):
                    page = page_for(config, slot)
                    slots.append({"slot": slot, "name": page.get("//", f"自定义 {slot}"),
                                  "topFrames": page["frames"]["frame_num"],
                                  "keyFrames": page["keyframes"]["frame_num"],
                                  "speedMs": page["speed_ms"], "brightness": page["lightness"]})
                results.append({"id": f"{source}:{path.name}", "snapshotId": f"{source}:{path.name}",
                                "createdAt": stamp, "filename": path.name, "slots": slots, "source": "last-written"})
            except (OSError, ValueError, TypeError, KeyError, BridgeError):
                continue
        return sorted(results, key=lambda value: value["createdAt"], reverse=True)[:100]

    def history(self, payload):
        return {"history": self.history_items(self.stored_product())}

    def fresh_baseline(self, payload, *, preserve_current_keymap=False):
        identity = self.discover(payload)
        require(identity is not None, "device_missing", "请通过 USB 连接键盘后重新检测。")
        config = self.stored_config(identity.product_id, required=True)
        validate_config(config, self.cli)
        self.require_current_led_baseline(identity.product_id, config)
        live, raw = self.read_live(identity.port)
        if not preserve_current_keymap:
            require(matrix(live) == matrix(config["key_layer"]), "baseline_keymap_changed",
                    "键盘上的键位与本机记录不同，已停止同步以保留当前键位。请先核对完整配置。")
        return identity, config, live, raw

    def prepare(self, payload, baseline_context=None, restore_source=None, restore_pages=None, *,
                built_in_pages=None, builtin_source=None, builtin_defaults=None):
        assignments = payload.get("assignments", [])
        changes = payload.get("keyChanges", [])
        preserve_current_keymap = payload.get("preserveCurrentKeymap", False)
        require(type(preserve_current_keymap) is bool, "invalid_keymap_policy", "保留当前键位选项必须是布尔值。")
        require(not preserve_current_keymap or changes == [], "invalid_keymap_policy",
                "保留当前键位的灯效同步不能同时包含键位修改。")
        require(restore_pages is None or isinstance(restore_pages, dict) and 1 <= len(restore_pages) <= 3 and
                all(type(slot) is int and 1 <= slot <= 3 and isinstance(page, dict) and page.get("page_index") == slot + 4
                    for slot, page in restore_pages.items()), "invalid_snapshot", "历史灯效页格式无效。")
        require(restore_pages is None or not assignments and not changes, "invalid_snapshot", "历史恢复不能混入其他配置修改。")
        require(built_in_pages is None or isinstance(built_in_pages, dict) and 1 <= len(built_in_pages) <= 5 and
                all(type(index) is int and 0 <= index <= 4 and isinstance(page, dict) and page.get("page_index") == index
                    for index, page in built_in_pages.items()), "invalid_builtin_pages", "内置模式页面计划无效。")
        require(built_in_pages is None or not assignments and not changes and restore_pages is None and preserve_current_keymap,
                "invalid_builtin_pages", "内置模式恢复只能修改所选内置页面，并必须保留当前键码。")
        require(isinstance(assignments, list) and isinstance(changes, list) and
                (assignments or changes or restore_pages or built_in_pages),
                "empty_plan", "请先选择灯效槽或需要修改的键位。")
        require(len(assignments) <= 3, "invalid_slots", "最多同步 3 个灯效槽。")
        slots = [integer(item.get("slot"), 1, 3, "自定义槽") for item in assignments if isinstance(item, dict)]
        require(len(slots) == len(assignments) and len(set(slots)) == len(slots),
                "invalid_slots", "同一个灯效槽不能重复选择。")
        if restore_pages is not None:
            slots = sorted(restore_pages)
        # Validate user-authored arrays before any USB operation.
        for item in assignments:
            design = item.get("design")
            require(isinstance(design, dict), "invalid_animation", "缺少灯效数据。")
            validate_animation(design.get("frames"), 200, "顶屏")
            validate_animation(design.get("keyframes"), 90, "轴灯")
            integer(item.get("brightness", 100), 0, 100, "亮度")
            integer(item.get("speedMs", design.get("speed_ms", 40)), 1, 32767, "播放间隔")
        for change in changes:
            require(isinstance(change, dict), "invalid_key_change", "键位修改格式无效。")
            integer(change.get("layer"), 0, 6, "键位层")
            integer(change.get("matrixIndex"), 0, 199, "键位编号")
            require(isinstance(change.get("code"), str) and KEY_RE.fullmatch(change["code"]),
                    "invalid_key_change", "键位编码需要使用 #MMPPUUUU 格式。")
        identity, stored, live, raw = baseline_context or self.fresh_baseline(
            payload, preserve_current_keymap=preserve_current_keymap)
        # Keep the original full record as the unreadable LED/extension baseline.
        # Only an explicit LED-only policy may accept a different live key matrix.
        # No CLI current record changes until the final write/readback succeeds.
        before = copy.deepcopy(stored)
        before["key_layer"]["valid"] = 1
        for index, layer in enumerate(live["layer_data"]):
            before["key_layer"]["layer_data"][index]["layer"] = copy.deepcopy(layer["layer"])
        physical_positions = {key["matrix_index"] for key in self.layout()}
        differences = [(layer_index, index)
                       for layer_index, (old, current) in enumerate(zip(stored["key_layer"]["layer_data"], live["layer_data"]))
                       for index, (old_code, current_code) in enumerate(zip(old["layer"], current["layer"]))
                       if old_code.upper() != current_code.upper()]
        physical_differences = sum(index in physical_positions for _, index in differences)
        preservation = {"source": "live", "comparedKeycodes": 1400,
                        "differentFromStored": len(differences), "differentPhysicalBindings": physical_differences,
                        "differentInternalKeycodes": len(differences) - physical_differences,
                        "refreshApplied": bool(differences)}
        target = copy.deepcopy(before)
        if built_in_pages is not None:
            for index, standard_page in built_in_pages.items():
                overlay_fields(page_at(target, index), standard_page)
        if restore_pages is not None:
            for slot, historical_page in restore_pages.items():
                page = page_for(target, slot)
                page.clear()
                page.update(copy.deepcopy(historical_page))
        for item in assignments:
            design = item["design"]
            page = page_for(target, item["slot"])
            for field in ("frames", "keyframes"):
                frames = design[field]
                page[field] = {"valid": 1, "frame_num": len(frames),
                               "frame_data": [{"frame_index": i, "frame_RGB": copy.deepcopy(frame)} for i, frame in enumerate(frames)]}
            page["lightness"] = item.get("brightness", 100)
            page["speed_ms"] = item.get("speedMs", design.get("speed_ms", 40))
            page["valid"] = True
            page["word_page"] = {"valid": 0, "word_len": 0, "unicode": []}
        allowed = {key["matrix_index"] for key in self.layout()} if changes else set()
        seen_changes = set()
        for change in changes:
            pair = (change["layer"], change["matrixIndex"])
            require(pair not in seen_changes and pair[1] in allowed, "invalid_key_change", "只能修改实体键，且同一键位不能重复设置。")
            seen_changes.add(pair)
            target["key_layer"]["layer_data"][pair[0]]["layer"][pair[1]] = change["code"].upper()
        fp = validate_config(target, self.cli)
        unchanged = copy.deepcopy(target)
        if built_in_pages is not None:
            for index in built_in_pages:
                page = page_at(unchanged, index)
                page.clear()
                page.update(copy.deepcopy(page_at(before, index)))
        for slot in slots:
            page, old = page_for(unchanged, slot), page_for(before, slot)
            if restore_pages is not None:
                page.clear()
                page.update(copy.deepcopy(old))
            else:
                for field in ("frames", "keyframes", "speed_ms", "lightness", "valid", "word_page"):
                    page[field] = copy.deepcopy(old[field])
        for change in changes:
            layer, index = change["layer"], change["matrixIndex"]
            unchanged["key_layer"]["layer_data"][layer]["layer"][index] = before["key_layer"]["layer_data"][layer]["layer"][index]
        require(unchanged == before, "unexpected_mutation", "同步计划包含未授权的配置变化。")
        token = uuid.uuid4().hex
        folder = self.state_dir / "plans" / token
        folder.mkdir(parents=True, exist_ok=False)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        backup = self.state_dir / "backups" / f"{stamp}--{token}.json"
        atomic_json(backup, {**before, "_studio_product_id": identity.product_id})
        atomic_json(folder / "stored-before.json", stored)
        atomic_json(folder / "before.json", before)
        atomic_json(folder / "target.json", target)
        (folder / "before.raw").write_bytes(raw)
        metadata = {"planVersion": 2, "token": token, "createdAt": now_iso(), "createdTimestamp": time.time(),
                    "status": "prepared", "productId": identity.product_id, "firmware": identity.version,
                    "port": identity.port, "storedBaselineHash": digest(stored),
                    "beforeHash": digest(before), "targetHash": digest(target),
                    "liveKeymapHash": hashlib.sha256(matrix(live)).hexdigest(), "backupPath": str(backup),
                    "changedSlots": sorted(slots), "keyChangeCount": len(changes), "totalFrames": fp.total,
                    "restoreSource": restore_source, "keymapPreservation": preservation}
        extra = {}
        if built_in_pages is not None:
            indices = sorted(built_in_pages)
            require(isinstance(builtin_defaults, dict) and builtin_defaults.get("source") == builtin_source,
                    "builtin_defaults_invalid", "内置模式恢复缺少可核对的官网标准配置来源。")
            atomic_json(folder / "builtin-defaults.json", builtin_defaults)
            explicit_diff = []
            for index in indices:
                position = next(i for i, page in enumerate(before["page_data"]) if page["page_index"] == index)
                explicit_diff.extend(configuration_diff(page_at(before, index), page_at(target, index),
                                                        f"/page_data/{position}"))
            extra = {"kind": "builtin-modes", "changedBuiltinPages": indices, "appliedSlots": [],
                     "builtinSummary": self.builtin_summary(target, indices), "explicitDiff": explicit_diff,
                     "builtinSource": copy.deepcopy(builtin_source)}
            metadata.update(extra)
            metadata["builtinDefaultsHash"] = digest(builtin_defaults)
        atomic_json(folder / "plan.json", metadata)
        summary = [{"slot": item["slot"], "name": item["design"].get("name", f"自定义 {item['slot']}"),
                    "topFrames": len(item["design"]["frames"]), "keyFrames": len(item["design"]["keyframes"]),
                    "brightness": item.get("brightness", 100),
                    "speedMs": item.get("speedMs", item["design"].get("speed_ms", 40))} for item in assignments]
        if restore_pages is not None:
            summary = [{"slot": slot, "name": str(page.get("//", f"历史灯效 {slot}"))[:256],
                        "topFrames": page["frames"]["frame_num"], "keyFrames": page["keyframes"]["frame_num"],
                        "brightness": page["lightness"], "speedMs": page["speed_ms"],
                        "enabled": bool(page["valid"]), "wordEnabled": bool(page.get("word_page", {}).get("valid"))}
                       for slot, page in sorted(restore_pages.items())]
        return {**extra, "token": token, "changedSlots": sorted(slots), "totalFrames": fp.total,
                "estimatedSeconds": math.ceil(fp.total * self.cli["cb_write"].WRITE_DELAY + 20),
                "backupPath": str(backup), "summary": summary, "keyChangeCount": len(changes),
                "config": self.provenance(target, "prepared"), "device": self.device_dict(identity),
                "keymap": self.keymap_view(live),
                "keymapPreservation": preservation,
                "ledSource": "last-written", "status": "prepared"}

    def plan(self, payload):
        require(payload.get("keyChanges", []) == [], "invalid_keymap_policy",
                "灯效计划保留全部当前键位；请从独立键位页面准备键位修改。")
        return self.prepare(payload)

    def builtInPlan(self, payload):
        source_hash = payload.get("sourceHash")
        require(isinstance(source_hash, str) and re.fullmatch(r"[a-f0-9]{64}", source_hash),
                "configuration_changed", "请先读取这把键盘的当前 JSON，再准备内置模式恢复。")
        indices = payload.get("pageIndices")
        require(isinstance(indices, list) and 1 <= len(indices) <= 5 and
                all(type(index) is int and 0 <= index <= 4 for index in indices) and len(set(indices)) == len(indices),
                "invalid_builtin_pages", "请选择不重复的内置模式页面 0–4。")
        require(payload.get("assignments", []) == [] and payload.get("keyChanges", []) == [] and
                payload.get("preserveCurrentKeymap", True) is True,
                "invalid_builtin_pages", "内置模式恢复不能混入作品、键位或任意 JSON 修改。")
        defaults = self.built_in_defaults()
        context = self.fresh_baseline(payload, preserve_current_keymap=True)
        require(digest(context[1]) == source_hash, "configuration_changed", "当前 JSON 已变化，请重新读取后再准备恢复。")
        pages = {index: copy.deepcopy(defaults["pages"][index]) for index in indices}
        return self.prepare({"preserveCurrentKeymap": True}, context,
                            built_in_pages=pages, builtin_source=defaults["source"], builtin_defaults=defaults)

    def require_no_current_record(self, pid):
        # A null/invalid record, directory, or dangling symlink is still an
        # existing record. Never reinterpret parse failure as a first setup.
        path = Path(self.cli["cb_store"].current_path(pid))
        try:
            path.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise BridgeError("initialization_store_unknown", "无法确认本机配置记录是否存在，已停止首次配置。",
                              reason=str(error)) from error
        raise BridgeError("initialization_record_exists", "本机已有这款键盘的配置记录，请使用普通同步；无效记录也不能自动覆盖。")

    def initialization_marker(self, pid):
        # cb_store validates product IDs before constructing their path. Reuse
        # its directory name so no product ID can escape application state.
        key = Path(self.cli["cb_store"].current_path(pid)).parent.name
        return self.state_dir / "initialization-state" / f"{key}.json"

    def require_unstarted_initialization(self, pid):
        marker = self.initialization_marker(pid)
        try:
            marker.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise BridgeError("initialization_unresolved", "无法核对此前首次配置的结果，不能再次初始化。",
                              reason=str(error)) from error
        raise BridgeError("initialization_unresolved",
                          "此前首次配置已经开始，当前缺少可核对的完整记录。请保留键位快照与目标配置，"
                          "通过可信 CLI 修复完整配置记录后再同步；不能把现在的键位当作首次配置前的可信状态。")

    def initializePlan(self, payload):
        require(payload.get("preserveCurrentKeymap") is True and payload.get("keyChanges", []) == [],
                "invalid_keymap_policy", "首次配置必须原样保留当前 1400 个键码，不能包含键位修改。")
        assignments = payload.get("assignments")
        require(isinstance(assignments, list) and 1 <= len(assignments) <= 3,
                "invalid_slots", "首次配置需要选择 1–3 个自定义灯效槽。")
        slots = [integer(item.get("slot"), 1, 3, "自定义槽") for item in assignments if isinstance(item, dict)]
        require(len(slots) == len(assignments) and len(set(slots)) == len(slots),
                "invalid_slots", "同一个灯效槽不能重复选择。")
        for item in assignments:
            design = item.get("design")
            require(isinstance(design, dict), "invalid_animation", "缺少灯效数据。")
            validate_animation(design.get("frames"), 200, "顶屏")
            validate_animation(design.get("keyframes"), 90, "轴灯")
            integer(item.get("brightness", 100), 0, 100, "亮度")
            integer(item.get("speedMs", design.get("speed_ms", 40)), 1, 32767, "播放间隔")
        identity = self.discover()
        require(identity is not None, "device_missing", "请通过 USB 连接键盘后重新检测。")
        require(not payload.get("port") or identity.port == payload["port"],
                "device_changed", "所选 USB 键盘已变化，请重新检测。")
        self.require_no_current_record(identity.product_id)
        self.require_unstarted_initialization(identity.product_id)
        live, raw = self.read_live(identity.port)
        defaults = self.built_in_defaults()
        target = initial_configuration(identity.product_id, live, defaults["pages"])
        names = {}
        for item in assignments:
            design = item["design"]
            page = page_for(target, item["slot"])
            for field in ("frames", "keyframes"):
                frames = design[field]
                page[field] = {"valid": 1, "frame_num": len(frames),
                               "frame_data": [{"frame_index": i, "frame_RGB": copy.deepcopy(frame)}
                                              for i, frame in enumerate(frames)]}
            page.update(valid=True, lightness=item.get("brightness", 100),
                        speed_ms=item.get("speedMs", design.get("speed_ms", 40)))
            names[item["slot"]] = str(design.get("name", f"自定义 {item['slot']}"))[:256]
        applied_slots = sorted(slots)
        fp = validate_initial_configuration(target, live, applied_slots, self.cli, defaults["pages"])
        self.require_no_current_record(identity.product_id)
        token = uuid.uuid4().hex
        folder = self.state_dir / "plans" / token
        folder.mkdir(parents=True, exist_ok=False)
        snapshot_path = folder / "live-keymap.json"
        snapshot = {"scope": "live-keymap-only", "productId": identity.product_id,
                    "firmware": identity.version, "port": identity.port, "capturedAt": now_iso(),
                    "key_layer": live, "ledSource": "unknown-before-initialization"}
        atomic_json(snapshot_path, snapshot)
        (folder / "live-keymap.raw").write_bytes(raw)
        atomic_json(folder / "target.json", target)
        atomic_json(folder / "builtin-defaults.json", defaults)
        preservation = {"source": "live", "comparedKeycodes": 1400, "preservedKeycodes": 1400,
                        "storedComparisonAvailable": False, "refreshApplied": False}
        summary = [{"slot": slot, "name": names.get(slot, f"自定义 {slot}（停用 / 黑色）"),
                    "topFrames": page_for(target, slot)["frames"]["frame_num"],
                    "keyFrames": page_for(target, slot)["keyframes"]["frame_num"],
                    "brightness": page_for(target, slot)["lightness"],
                    "speedMs": page_for(target, slot)["speed_ms"],
                    "enabled": slot in slots, "applied": slot in slots, "wordEnabled": False}
                   for slot in (1, 2, 3)]
        details = {"initialization": True, "backupScope": "live-keymap-only", "appliedSlots": applied_slots,
                   "changedSlots": [1, 2, 3], "keyChangeCount": 0, "backupPath": str(snapshot_path),
                   "ledSource": "unknown-before-initialization", "limitations": list(INITIALIZATION_LIMITATIONS),
                   "keymapPreservation": preservation, "summary": summary,
                   "builtinSummary": self.builtin_summary(target), "builtinSource": copy.deepcopy(defaults["source"])}
        metadata = {**details, "planVersion": 3, "token": token, "createdAt": now_iso(), "createdTimestamp": time.time(),
                    "status": "prepared", "productId": identity.product_id, "firmware": identity.version,
                    "port": identity.port, "targetHash": digest(target), "liveSnapshotHash": digest(snapshot),
                    "builtinDefaultsHash": digest(defaults),
                    "liveRawHash": hashlib.sha256(raw).hexdigest(),
                    "liveKeymapHash": hashlib.sha256(matrix(live)).hexdigest(), "totalFrames": fp.total}
        atomic_json(folder / "plan.json", metadata)
        config = copy.deepcopy(target)
        config["_provenance"] = {"led": "unknown-before-initialization", "keymap": "live"}
        return {**details, "token": token, "totalFrames": fp.total, "status": "prepared",
                "estimatedSeconds": math.ceil(fp.total * self.cli["cb_write"].WRITE_DELAY + 20),
                "config": config, "device": self.device_dict(identity), "keymap": self.keymap_view(live)}

    def snapshot_path(self, snapshot_id, pid):
        require(isinstance(snapshot_id, str) and ":" in snapshot_id, "invalid_snapshot", "请选择有效的历史记录。")
        source, filename = snapshot_id.split(":", 1)
        require(source in ("cli", "app") and SNAPSHOT_RE.fullmatch(filename) and ".." not in filename,
                "invalid_snapshot", "历史记录编号无效。")
        directory = self.cli["cb_store"].history_dir(pid) if source == "cli" else self.state_dir / "backups"
        path = directory / filename
        require(path.is_file() and path.resolve().parent == directory.resolve(), "snapshot_missing", "历史记录已不存在。")
        return path

    def restorePlan(self, payload):
        require(payload.get("preserveKeymap", True) is True, "restore_keymap_not_supported",
                "历史恢复只恢复灯效，键位保留当前配置。")
        require(payload.get("keyChanges", []) == [], "invalid_keymap_policy",
                "保留当前键位的历史恢复不能同时包含键位修改。")
        context = self.fresh_baseline(payload, preserve_current_keymap=True)
        identity = context[0]
        snapshot_id = payload.get("snapshotId")
        snapshot = load_json(self.snapshot_path(snapshot_id, identity.product_id))
        require(snapshot.get("_studio_product_id", identity.product_id) == identity.product_id,
                "snapshot_identity", "历史记录属于另一款键盘。")
        pages = {}
        for slot in (1, 2, 3):
            page = page_for(snapshot, slot)
            pages[slot] = copy.deepcopy(page)
        # Restore the historical custom pages exactly, including disabled, text
        # and empty pages. Global settings and keys still come from the fresh
        # current baseline, and final target validation precedes any write.
        return self.prepare({"preserveCurrentKeymap": True}, context, restore_source=snapshot_id, restore_pages=pages)

    def send_config(self, port, fp, pre_start=None):
        """CLI-equivalent serial write, with CRC/header checks and real frame progress."""
        writer, protocol = self.cli["cb_write"], self.cli["cb_protocol"]
        ser = writer.serial.Serial(port, baudrate=self.cli["cb_device"].BAUD, timeout=10,
                                   write_timeout=10, exclusive=True)
        try:
            time.sleep(0.1)
            ser.reset_input_buffer()
            self.event("starting", 0, fp.total)
            if pre_start is not None:
                pre_start()
            ser.write(protocol.build_frame(*writer.CMD_JSON_START))
            ser.flush()
            reply = ser.read(64)
            require(len(reply) == 64 and reply[:3] == b"\x01\x05\x01" and protocol.crc_ok(reply),
                    "start_ack_failed", "键盘未确认开始接收，已停止同步。", deviceMayHaveChanged=True)
            sections = [(name, count) for name, count in fp.sections if count]
            section = 0
            end = sections[0][1]
            for transferred, frame in enumerate(fp.frames, 1):
                time.sleep(writer.WRITE_DELAY)
                require(ser.write(frame) == 64, "short_usb_write", "USB 数据发送中断，请检查连接。", deviceMayHaveChanged=True)
                if transferred % 32 == 0 or transferred == end or transferred == fp.total:
                    self.event(sections[section][0], transferred, fp.total)
                if transferred == end and section + 1 < len(sections):
                    section += 1
                    end += sections[section][1]
            ser.flush()
            time.sleep(writer.WRITE_DELAY)
            ser.write(protocol.build_frame(*writer.CMD_JSON_END, fp.total.to_bytes(4, "big", signed=True)))
            ser.flush()
            self.event("committing", fp.total, fp.total)
            reply = ser.read(64)
            for _ in range(15):
                if len(reply) == 64 and reply[:3] == b"\x01\x06\x01" and protocol.crc_ok(reply):
                    return reply
                if not (len(reply) == 64 and reply[:3] == b"\x01\x06\x02" and protocol.crc_ok(reply)):
                    break
                time.sleep(1)
                reply = ser.read(64)
            raise BridgeError("end_ack_failed", "键盘没有返回有效的完成回执，请重新检测。", deviceMayHaveChanged=True)
        finally:
            ser.close()

    def execute(self, payload):
        token = payload.get("token")
        require(isinstance(token, str) and TOKEN_RE.fullmatch(token), "invalid_plan", "同步计划无效，请重新准备。")
        folder = self.state_dir / "plans" / token
        require((folder / "plan.json").is_file(), "plan_missing", "同步计划已不存在，请重新准备。")
        metadata = load_json(folder / "plan.json")
        require(metadata.get("planVersion") in (2, 3), "plan_version_unsupported",
                "这个同步计划来自旧版本，请重新准备后再同步。")
        require(metadata.get("status") == "prepared" and metadata.get("token") == token,
                "plan_consumed", "这个同步计划已经执行或失效，请重新准备。")
        require(0 <= time.time() - metadata.get("createdTimestamp", 0) <= PLAN_LIFETIME_SECONDS,
                "plan_expired", "同步计划已过期，请重新准备。")
        if metadata["planVersion"] == 3:
            return self.execute_initialization(payload, folder, metadata)
        require(all((folder / name).is_file() for name in ("stored-before.json", "before.json", "target.json")),
                "plan_tampered", "同步计划文件不完整，请重新准备。")
        stored_before = load_json(folder / "stored-before.json")
        before, target = load_json(folder / "before.json"), load_json(folder / "target.json")
        require(digest(stored_before) == metadata.get("storedBaselineHash") and
                digest(before) == metadata.get("beforeHash") and digest(target) == metadata.get("targetHash"),
                "plan_tampered", "同步计划内容发生变化，请重新准备。")
        if metadata.get("kind") == "keymap" or "keyChanges" in metadata:
            key_summary = self.keymap_change_summary(before, target)
            unchanged = copy.deepcopy(target)
            for old, current in zip(before["key_layer"]["layer_data"], unchanged["key_layer"]["layer_data"]):
                current["layer"] = copy.deepcopy(old["layer"])
            require(metadata.get("kind") == "keymap" and key_summary and
                    metadata.get("changedSlots") == [] and unchanged == before and
                    type(metadata.get("keyChangeCount")) is int and metadata["keyChangeCount"] == len(key_summary) and
                    metadata.get("keyChanges") == key_summary and
                    metadata.get("expectedKeymapHash") == metadata.get("liveKeymapHash") ==
                    hashlib.sha256(matrix(before["key_layer"])).hexdigest(),
                    "plan_tampered", "键位计划包含未确认的键位或灯效修改，请重新准备。")
        else:
            require(metadata.get("keyChangeCount") == 0 and target.get("key_layer") == before.get("key_layer"), "plan_tampered",
                    "灯效计划不能包含键位修改，请从独立键位页面重新准备。")
        builtin_artifact = folder / "builtin-defaults.json"
        if builtin_artifact.exists() or metadata.get("kind") == "builtin-modes" or "changedBuiltinPages" in metadata or "builtinDefaultsHash" in metadata:
            indices = metadata.get("changedBuiltinPages")
            require(metadata.get("kind") == "builtin-modes" and builtin_artifact.is_file() and
                    isinstance(indices, list) and 1 <= len(indices) <= 5 and
                    all(type(index) is int and 0 <= index <= 4 for index in indices) and len(set(indices)) == len(indices) and
                    metadata.get("changedSlots") == [] and metadata.get("appliedSlots") == [] and
                    metadata.get("keyChangeCount") == 0 and isinstance(metadata.get("builtinSource"), dict),
                    "plan_tampered", "内置模式同步计划标记发生变化，请重新准备。")
            defaults = load_json(builtin_artifact)
            require(digest(defaults) == metadata.get("builtinDefaultsHash") and defaults == self.built_in_defaults() and
                    metadata["builtinSource"] == defaults["source"],
                    "plan_tampered", "内置模式计划的官网标准配置来源发生变化，请重新准备。")
            unchanged, expected, explicit_diff = copy.deepcopy(target), copy.deepcopy(before), []
            for index in indices:
                position = next(i for i, page in enumerate(before["page_data"]) if page["page_index"] == index)
                explicit_diff.extend(configuration_diff(page_at(before, index), page_at(target, index), f"/page_data/{position}"))
                page = page_at(unchanged, index)
                page.clear()
                page.update(copy.deepcopy(page_at(before, index)))
                overlay_fields(page_at(expected, index), defaults["pages"][index])
            require(target == expected and unchanged == before and metadata.get("explicitDiff") == explicit_diff and
                    metadata.get("builtinSummary") == self.builtin_summary(target, indices),
                    "plan_tampered", "内置模式计划包含未授权的 JSON 修改或差异报告发生变化。")
        current = self.stored_config(metadata["productId"], required=True)
        require(digest(current) == metadata["storedBaselineHash"], "baseline_changed", "本机配置已更新，请重新准备同步。")
        self.require_current_led_baseline(metadata["productId"], current)
        identity = self.discover({"port": metadata["port"]})
        require(identity is not None and identity.product_id == metadata["productId"] and identity.version == metadata["firmware"],
                "device_changed", "连接的键盘或固件发生变化，请重新检测。")
        fp = validate_config(target, self.cli)
        require(fp.total == metadata["totalFrames"], "plan_tampered", "同步数据量发生变化，请重新准备。")
        # Read exactly once after encoding, close to JSON_START. Never silently
        # refresh a reviewed plan if the device keymap changed in the meantime.
        live, raw = self.read_live(identity.port)
        require(hashlib.sha256(matrix(live)).hexdigest() == metadata["liveKeymapHash"],
                "keymap_changed", "键盘上的键位已变化，请重新准备同步。")
        # Final store comparison immediately before the destructive JSON_START.
        require(digest(self.stored_config(identity.product_id, required=True)) == metadata["storedBaselineHash"],
                "baseline_changed", "本机配置已更新，请重新准备同步。")
        metadata.update(status="executing", startedAt=now_iso(), startedTimestamp=time.time(),
                        currentRecordMtimeNs=self.current_record_mtime_ns(identity.product_id))
        atomic_json(folder / "plan.json", metadata)
        return self._execute_configuration(folder, metadata, identity, target, fp)

    def execute_initialization(self, payload, folder, metadata):
        require(payload.get("confirmInitialization") is True, "initialization_confirmation_required",
                "首次配置会替换未知原灯效与其他模式，请先阅读限制并明确确认。")
        require(metadata.get("initialization") is True and metadata.get("backupScope") == "live-keymap-only" and
                metadata.get("changedSlots") == [1, 2, 3] and metadata.get("keyChangeCount") == 0 and
                metadata.get("ledSource") == "unknown-before-initialization" and
                metadata.get("limitations") == list(INITIALIZATION_LIMITATIONS) and
                metadata.get("backupPath") == str(folder / "live-keymap.json"),
                "plan_tampered", "首次配置计划标记发生变化，请重新准备。")
        require(all((folder / name).is_file() for name in ("target.json", "live-keymap.json", "live-keymap.raw", "builtin-defaults.json")),
                "plan_tampered", "首次配置计划文件不完整，请重新准备。")
        target, snapshot = load_json(folder / "target.json"), load_json(folder / "live-keymap.json")
        defaults = load_json(folder / "builtin-defaults.json")
        raw = (folder / "live-keymap.raw").read_bytes()
        require(digest(target) == metadata.get("targetHash") and digest(snapshot) == metadata.get("liveSnapshotHash") and
                digest(defaults) == metadata.get("builtinDefaultsHash") and
                defaults == self.built_in_defaults() and metadata.get("builtinSource") == defaults["source"] and
                hashlib.sha256(raw).hexdigest() == metadata.get("liveRawHash") and
                snapshot.get("scope") == "live-keymap-only" and snapshot.get("productId") == metadata["productId"] and
                snapshot.get("firmware") == metadata["firmware"] and snapshot.get("port") == metadata["port"] and
                target.get("product_info", {}).get("product_id") == metadata["productId"],
                "plan_tampered", "首次配置内容或键位快照发生变化，请重新准备。")
        live_before = snapshot.get("key_layer")
        require(hashlib.sha256(matrix(live_before)).hexdigest() == metadata.get("liveKeymapHash"),
                "plan_tampered", "首次配置键位快照校验失败，请重新准备。")
        self.require_no_current_record(metadata["productId"])
        self.require_unstarted_initialization(metadata["productId"])
        # Scan every candidate again: selecting the original port must not hide
        # a second keyboard that was attached after review.
        identity = self.discover()
        require(identity is not None and identity.product_id == metadata["productId"] and
                identity.version == metadata["firmware"] and identity.port == metadata["port"],
                "device_changed", "连接的键盘、USB 端口或固件发生变化，请重新检测。")
        fp = validate_initial_configuration(target, live_before, metadata.get("appliedSlots"), self.cli, defaults["pages"])
        require(fp.total == metadata["totalFrames"], "plan_tampered", "首次配置数据量发生变化，请重新准备。")
        live, _ = self.read_live(identity.port)
        require(hashlib.sha256(matrix(live)).hexdigest() == metadata["liveKeymapHash"] and
                matrix(live) == matrix(target["key_layer"]),
                "keymap_changed", "键盘上的键位已变化，请重新准备首次配置。")
        self.require_no_current_record(identity.product_id)
        # This durable, separate marker precedes JSON_START. Even if completion
        # and failure reports cannot be saved, another init cannot trust the
        # potentially reset matrix as the original device state.
        atomic_json(self.initialization_marker(identity.product_id),
                    {"initialization": True, "productId": identity.product_id, "token": metadata["token"],
                     "startedAt": now_iso(), "targetHash": metadata["targetHash"], "scope": "live-keymap-only"})
        metadata.update(status="executing", startedAt=now_iso(), startedTimestamp=time.time())
        atomic_json(folder / "plan.json", metadata)
        return self._execute_configuration(folder, metadata, identity, target, fp)

    def _execute_configuration(self, folder, metadata, identity, target, fp):
        try:
            if metadata.get("initialization") is True:
                ack = self.send_config(identity.port, fp,
                                       pre_start=lambda: self.require_no_current_record(identity.product_id))
            else:
                ack = self.send_config(identity.port, fp)
            self.event("verifying", fp.total, fp.total)
            time.sleep(self.cli["cb_write"].SETTLE_SECONDS)
            attempts, archive_warnings, matched = [], [], False
            for attempt in range(3):
                try:
                    after = self.cli["cb_device"].probe(identity.port, full=True)
                    require(after is not None and after.product_id == identity.product_id and after.version == identity.version,
                            "device_changed", "提交后键盘身份核对失败。")
                    readback, captured = self.read_live(identity.port)
                    matched = matrix(readback) == matrix(target["key_layer"])
                    attempts.append({"attempt": attempt + 1, "keymapMatch": matched, "completeKeycodes": 1400})
                    # Local diagnostic archives do not determine whether the
                    # complete device readback matches the submitted keymap.
                    try:
                        (folder / f"after-{attempt + 1}.raw").write_bytes(captured)
                    except Exception as error:
                        archive_warnings.append(f"第 {attempt + 1} 次键位读回归档未保存：{error}")
                except (BridgeError, OSError, ValueError) as error:
                    attempts.append({"attempt": attempt + 1, "keymapMatch": False, "reason": str(error)})
                if matched:
                    break
                if attempt < 2:
                    time.sleep(5)
            require(matched, "verification_failed", "键盘已接收数据，但完整键位核对未通过。请保留同步快照并重新检测。",
                    deviceMayHaveChanged=True, deviceAck=True, backupPath=metadata["backupPath"], attempts=attempts)
        except Exception as error:
            metadata.update(status="failed", failedAt=now_iso(), error=str(error))
            atomic_json(folder / "plan.json", metadata)
            if isinstance(error, BridgeError):
                raise
            raise BridgeError("write_interrupted", "同步中断，键盘可能已经接收部分数据。请保留同步快照并重新检测。",
                              deviceMayHaveChanged=True, backupPath=metadata["backupPath"], reason=str(error)) from error
        # Device success is now established by an ACK and a complete readback.
        # A later local bookkeeping failure cannot turn it into a USB failure.
        return self._complete_verified_write(folder, metadata, identity, target, fp, ack, attempts, archive_warnings)

    def _complete_verified_write(self, folder, metadata, identity, target, fp, ack, attempts, archive_warnings=None):
        captured_out, captured_err = io.StringIO(), io.StringIO()
        store_warnings, report_warnings = [], list(archive_warnings or [])
        try:
            with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
                self.cli["cb_write"]._record_write(identity.product_id, target, identity.version)
        except Exception as error:
            store_warnings.append(str(error))
        if captured_err.getvalue().strip():
            store_warnings.append(captured_err.getvalue().strip())
        try:
            state_stored = digest(self.stored_config(identity.product_id) or {}) == digest(target)
        except Exception as error:
            state_stored = False
            store_warnings.append(str(error))
        try:
            device = self.device_dict(identity)
        except Exception as error:
            device = {"productId": identity.product_id, "firmware": identity.version,
                      "port": identity.port, "connected": True, "lastSeen": None}
            store_warnings.append(str(error))
        report = {"success": True, "deviceAck": True, "keymapMatch": True, "stateStored": state_stored,
                  "reportStored": not report_warnings, "backupPath": metadata["backupPath"], "changedSlots": metadata["changedSlots"],
                  "keyChangeCount": metadata["keyChangeCount"], "device": device,
                  "writtenAt": now_iso(), "totalFrames": fp.total, "readbackAttempts": attempts,
                  "completedTimestamp": time.time(), "verifiedTargetHash": metadata["targetHash"],
                  "ledVerification": "protocol-ack-only", "ledSource": "last-written",
                  "ackHex": ack.hex(), "cliLog": captured_out.getvalue().strip()}
        if metadata.get("initialization") is True:
            report.update(initialization=True, backupScope="live-keymap-only", appliedSlots=metadata["appliedSlots"],
                          ledBeforeSource="unknown-before-initialization", limitations=metadata["limitations"])
        if metadata.get("kind") == "builtin-modes":
            report.update(kind="builtin-modes", changedBuiltinPages=metadata["changedBuiltinPages"], appliedSlots=[],
                          builtinSummary=metadata["builtinSummary"], explicitDiff=metadata["explicitDiff"],
                          builtinSource=metadata["builtinSource"])
        if metadata.get("kind") == "keymap":
            report.update(kind="keymap", keyChanges=metadata["keyChanges"],
                          keymap={**self.keymap_view(target["key_layer"]), "verifiedReadback": True},
                          config=self.provenance(target, "live"))

        def warnings():
            if store_warnings or not state_stored or report_warnings:
                report["warning"] = "键盘已同步，本机记录或同步报告未能完整保存，请保留同步快照。"
            if store_warnings:
                report["storeWarning"] = "\n".join(store_warnings)
            if report_warnings:
                report["reportWarning"] = "\n".join(report_warnings)

        metadata.update(status="complete", completedAt=report["writtenAt"], completedTimestamp=report["completedTimestamp"],
                        deviceAck=True, keymapMatch=True, stateStored=state_stored, verifiedTargetHash=metadata["targetHash"])
        try:
            atomic_json(folder / "plan.json", metadata)
        except Exception as error:
            report["reportStored"] = False
            report_warnings.append(str(error))
        warnings()
        try:
            atomic_json(folder / "result.json", report)
        except Exception as error:
            report["reportStored"] = False
            report_warnings.append(str(error))
            warnings()
        try:
            self.event("complete", fp.total, fp.total)
        except Exception as error:
            report_warnings.append(str(error))
            warnings()
        return report

    def companion_action(self, method, payload):
        from companion import Wardrobe, CompanionError
        from speech_input import SpeechError
        try:
            with operation_lock(self.state_dir / ".companion-image.lock"):
                return getattr(Wardrobe(self.state_dir, self.resource_dir), method)(payload)
        except CompanionError as error:
            raise BridgeError("companion_failed", str(error)) from None
        except SpeechError:
            raise BridgeError("companion_failed", "已有语音 Key 无法读取，请重新填写生图 Key。") from None
        except (OSError, ValueError, TypeError):
            raise BridgeError("companion_failed", "衣装操作未完成，请检查连接后重试。") from None

    def companionImageSettings(self, payload): return self.companion_action("settings", payload)
    def companionImageSave(self, payload): return self.companion_action("save", payload)
    def companionImageReveal(self, payload): return self.companion_action("reveal", payload)
    def companionOutfitGenerate(self, payload): return self.companion_action("generate", payload)
    def companionOutfitDelete(self, payload): return self.companion_action("delete", payload)

    def speech_action(self, method, payload):
        from speech_input import SpeechSettings, SpeechError, transcribe
        try:
            settings = SpeechSettings(self.state_dir)
            # Reading the active profile is safe without creating a lock file:
            # settings are replaced atomically, so a concurrent save yields
            # either the previous or the complete new JSON document. This is
            # also needed before enabling MiaoCall's permission-gated key tap,
            # since profile inspection itself must not require write access.
            if method == "get":
                return settings.get()
            with operation_lock(self.state_dir / ".voice-settings.lock"):
                if method == "transcribe":
                    return transcribe(settings, payload)
                return getattr(settings, method)(payload)
        except SpeechError as error:
            raise BridgeError(error.code, error.message, **error.details) from None
        except (OSError, ValueError, TypeError):
            raise BridgeError("voice_operation_failed", "语音操作未完成，请检查连接后重试。") from None

    def voiceSettings(self, payload):
        return self.speech_action("get", payload)

    def saveVoiceSettings(self, payload):
        return self.speech_action("save", payload)

    def revealVoiceKey(self, payload):
        return self.speech_action("reveal", payload)

    def deleteVoiceKey(self, payload):
        return self.speech_action("delete", payload)

    def transcribeVoice(self, payload):
        return self.speech_action("transcribe", payload)

    def setTime(self, payload):
        timezone_name = payload.get("timezone", "Asia/Shanghai")
        zone = resolve_timezone(timezone_name)
        identity = self.discover(payload)
        require(identity is not None, "device_missing", "请通过 USB 连接键盘。")
        offset = datetime.now(zone).utcoffset().total_seconds()
        whole_hours = int(offset / 3600)
        epoch = int(time.time()) + int(offset - whole_hours * 3600)
        rtc_payload = epoch.to_bytes(4, "big", signed=True) + bytes([0 if offset > 0 else 1 if offset < 0 else 2, abs(whole_hours)])
        timer, protocol = self.cli["cb_settime"], self.cli["cb_protocol"]
        ser = timer.serial.Serial(identity.port, baudrate=self.cli["cb_device"].BAUD, timeout=2,
                                  write_timeout=2, exclusive=True)
        try:
            time.sleep(0.1)
            ser.reset_input_buffer()
            time.sleep(0.005)
            ser.write(protocol.build_frame(1, 3, rtc_payload))
            ser.flush()
            reply = ser.read(64)
            require(len(reply) == 64 and reply[:3] == b"\x01\x03\x01" and protocol.crc_ok(reply),
                    "time_ack_failed", "键盘未确认时间同步，请重新检测。")
        finally:
            ser.close()
        return {"success": True, "deviceAck": True, "device": self.device_dict(identity),
                "timezone": timezone_name, "syncedAt": datetime.now(zone).isoformat(timespec="seconds")}


def main():
    configure_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=("bootstrap", "detect", "keymap", "keymapCatalog", "keymapPlan", "readConfiguration", "history", "plan", "builtInPlan", "initializePlan", "execute", "setTime", "restorePlan", "saveWorkspace", "testAIConnection", "generateAI", "prepareAIImages", "voiceSettings", "saveVoiceSettings", "revealVoiceKey", "deleteVoiceKey", "transcribeVoice", "miaoCallWorker", "companionImageSettings", "companionImageSave", "companionImageReveal", "companionOutfitGenerate", "companionOutfitDelete", "runtimeHealth"))
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--resource-dir", required=True)
    args = parser.parse_args()
    try:
        if args.action == "runtimeHealth":
            # A release check before Bridge initialization: no credentials,
            # device discovery, state files, or network connections are used.
            import ssl
            try:
                context = ssl.create_default_context()
                require(context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED,
                        "runtime_tls_invalid", "网络证书校验配置无效，请重新下载软件包。")
                certificates = context.cert_store_stats()["x509_ca"]
                require(certificates > 0, "runtime_tls_invalid", "网络证书组件缺失，请重新下载软件包。")
            except OSError:
                raise BridgeError("runtime_tls_incomplete", "网络证书组件不完整，请重新下载软件包。") from None
            emit({"result": {"tlsReady": True, "hostnameVerification": True,
                             "certificateVerification": True, "caCertificates": certificates}})
            return 0
        if args.action == "miaoCallWorker":
            # The task transport is interactive JSONL; unlike one-shot actions its
            # input stays open for bounded tool replies and cancellation.
            from miao_call import run as run_miao_call
            line = sys.stdin.readline(32769)
            require(len(line.encode("utf-8")) <= 32768, "input_too_large", "语音指令过长。")
            payload = json.loads(line or "{}")
            require(isinstance(payload, dict), "invalid_input", "语音指令格式无效。")
            result = run_miao_call(payload, emit, sys.stdin)
            emit({"result": result})
            return 0
        max_input = MAX_WORKSPACE_BYTES if args.action == "saveWorkspace" else MAX_INPUT_BYTES
        raw = sys.stdin.buffer.read(max_input + 1)
        require(len(raw) <= max_input, "input_too_large", "输入文件过大。")
        payload = json.loads(raw or b"{}")
        require(isinstance(payload, dict), "invalid_input", "输入需要是 JSON 对象。")
        bridge = Bridge(args.state_dir, args.resource_dir)
        # Native serializes actions; the lock also prevents a second app process
        # from interleaving a plan or write with this one.
        if args.action in ("plan", "keymapPlan", "builtInPlan", "initializePlan", "execute", "setTime", "restorePlan", "detect", "keymap", "readConfiguration"):
            with operation_lock(bridge.state_dir / ".operation.lock"):
                result = getattr(bridge, args.action)(payload)
        else:
            result = getattr(bridge, args.action)(payload)
        emit({"result": result})
        return 0
    except BridgeError as error:
        emit({"error": {"code": error.code, "message": error.message, "details": error.details}})
    except (OSError, ValueError, TypeError, KeyError) as error:
        emit({"error": {"code": "operation_failed", "message": "操作未完成，请检查连接和输入文件。", "details": {"reason": str(error)}}})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
