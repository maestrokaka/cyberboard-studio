#!/usr/bin/env python3
"""One-shot JSON-lines bridge to the locally installed Cyberboard CLI.

bootstrap/history are offline. detect/keymap are USB reads. plan/restorePlan
prepare a reviewable full configuration; only execute writes that configuration.
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
SNAPSHOT_RE = re.compile(r"^[A-Za-z0-9_.-]+\.json$")
RESERVED_LEDS = (57, 61, 74, 78, 82, 83, 84)
PLAN_LIFETIME_SECONDS = 30 * 60
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_WORKSPACE_BYTES = 32 * 1024 * 1024

# Source importlib tests and isolated Windows Python need the sibling modules.
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))


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


def validate_config(config, cli):
    require(isinstance(config, dict) and isinstance(config.get("page_data"), list),
            "invalid_baseline", "本机配置不是完整的键盘配置。")
    require(config.get("page_num") == len(config["page_data"]),
            "invalid_baseline", "本机配置的页面数不一致。")
    indices = [page.get("page_index") for page in config["page_data"]]
    require(len(set(indices)) == len(indices) and all(type(i) is int and 0 <= i <= 255 for i in indices),
            "invalid_baseline", "配置包含无效页面编号。")
    validate_layers(config.get("key_layer"))
    for page in config["page_data"]:
        integer(page.get("lightness"), 0, 100, "亮度")
        integer(page.get("speed_ms"), 0 if page.get("valid") in (0, False) else 1, 32767, "播放间隔")
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
    try:
        fp = cli["cb_write"].plan(config)
    except (KeyError, ValueError, TypeError, OverflowError) as error:
        raise BridgeError("invalid_config", "配置无法转换为键盘可接收的数据。", reason=str(error)) from error
    require(fp.total > 0 and all(len(frame) == 64 and cli["cb_protocol"].crc_ok(frame) for frame in fp.frames),
            "invalid_wire_frames", "配置校验未通过，未进行写入。")
    return fp


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
        from kimi_ai import AIError, KimiClient, configuration
        try:
            client = KimiClient(configuration(payload.get("ai")),
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
                "缺少 CLI 本机完整配置记录，不能安全保留其他灯效槽。请迁移这把键盘此前成功写入的完整配置记录；应用导入只导入灯效。")
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
                     "selectedId": selected, "targetSlot": target, "brief": brief, "palette": copy.deepcopy(palette),
                     "brightness": brightness, "speedMs": speed_ms, "exportFormat": export_format}
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
            workspace = self.validate_workspace(saved)
            workspace["savedAt"] = saved.get("savedAt")
            return workspace, None
        except (BridgeError, OSError, ValueError, TypeError, KeyError):
            return None, "保存的工作台草稿无法载入。原文件已保留，灯效与设备配置不受影响。"

    def saveWorkspace(self, payload):
        workspace = self.validate_workspace(payload)
        workspace.update(version=1, savedAt=now_iso())
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
        for port in ([named] if named else ports):
            info = device.probe(port, full=True)
            if info is not None and recognized(info.product_id) and not info.is_dongle:
                identities.append(info)
        require(len(identities) <= 1, "ambiguous_device", "检测到多把键盘，请只连接需要同步的一把。")
        return identities[0] if identities else None

    def read_live(self, port):
        frames = self.cli["cb_read"]._drain(port, (6, 9), timeout=1.5)
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

    def decode_binding(self, code, known):
        code = code.upper()
        if code in known:
            return {**known[code], "code": code}
        if code == "#00000000":
            return {"short": "—", "name": "未绑定", "code": code}
        mask, page, usage = int(code[1:3], 16), int(code[3:5], 16), int(code[5:9], 16)
        if page == 0x92:
            label, name = f"{usage:04X}", f"厂家功能 {usage:04X}（名称未确认）"
        else:
            table = self.cli["cb_keymap"].HID07 if page == 7 else self.cli["cb_keymap"].HID0C if page == 12 else {}
            label = table.get(usage, f"{page:02X}:{usage:04X}")
            name = label if usage in table else f"键码 {code}"
        if mask:
            label, name = "组合", f"修饰键 {mask:02X} + {name}"
        return {"short": label, "name": name, "code": code}

    def keymap_view(self, live):
        keys = copy.deepcopy(self.layout())
        known = {binding["code"].upper(): binding for key in keys for binding in key.get("bindings", [])
                 if isinstance(binding, dict) and KEY_RE.fullmatch(binding.get("code", ""))}
        for key in keys:
            key["bindings"] = [self.decode_binding(layer["layer"][key["matrix_index"]], known)
                               for layer in live["layer_data"]]
        return {**copy.deepcopy(live), "keys": keys, "source": "live", "physicalKeyCount": 81}

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

    def prepare(self, payload, baseline_context=None, restore_source=None, restore_pages=None):
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
        require(isinstance(assignments, list) and isinstance(changes, list) and (assignments or changes or restore_pages),
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
        return {"token": token, "changedSlots": sorted(slots), "totalFrames": fp.total,
                "estimatedSeconds": math.ceil(fp.total * self.cli["cb_write"].WRITE_DELAY + 20),
                "backupPath": str(backup), "summary": summary, "keyChangeCount": len(changes),
                "config": self.provenance(target, "prepared"), "device": self.device_dict(identity),
                "keymap": self.keymap_view(live),
                "keymapPreservation": preservation,
                "ledSource": "last-written", "status": "prepared"}

    def plan(self, payload):
        return self.prepare(payload)

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

    def send_config(self, port, fp):
        """CLI-equivalent serial write, with CRC/header checks and real frame progress."""
        writer, protocol = self.cli["cb_write"], self.cli["cb_protocol"]
        ser = writer.serial.Serial(port, baudrate=self.cli["cb_device"].BAUD, timeout=10,
                                   write_timeout=10, exclusive=True)
        try:
            time.sleep(0.1)
            ser.reset_input_buffer()
            self.event("starting", 0, fp.total)
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
        require(metadata.get("planVersion") == 2, "plan_version_unsupported",
                "这个同步计划来自旧版本，请重新准备后再同步。")
        require(metadata.get("status") == "prepared" and metadata.get("token") == token,
                "plan_consumed", "这个同步计划已经执行或失效，请重新准备。")
        require(0 <= time.time() - metadata.get("createdTimestamp", 0) <= PLAN_LIFETIME_SECONDS,
                "plan_expired", "同步计划已过期，请重新准备。")
        require(all((folder / name).is_file() for name in ("stored-before.json", "before.json", "target.json")),
                "plan_tampered", "同步计划文件不完整，请重新准备。")
        stored_before = load_json(folder / "stored-before.json")
        before, target = load_json(folder / "before.json"), load_json(folder / "target.json")
        require(digest(stored_before) == metadata.get("storedBaselineHash") and
                digest(before) == metadata.get("beforeHash") and digest(target) == metadata.get("targetHash"),
                "plan_tampered", "同步计划内容发生变化，请重新准备。")
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
        try:
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
            require(matched, "verification_failed", "键盘已接收数据，但完整键位核对未通过。请保留备份并重新检测。",
                    deviceMayHaveChanged=True, deviceAck=True, backupPath=metadata["backupPath"], attempts=attempts)
        except Exception as error:
            metadata.update(status="failed", failedAt=now_iso(), error=str(error))
            atomic_json(folder / "plan.json", metadata)
            if isinstance(error, BridgeError):
                raise
            raise BridgeError("write_interrupted", "同步中断，键盘可能已经接收部分数据。请保留备份并重新检测。",
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

        def warnings():
            if store_warnings or not state_stored or report_warnings:
                report["warning"] = "键盘已同步，本机记录或同步报告未能完整保存，请保留备份。"
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
    parser.add_argument("--action", required=True, choices=("bootstrap", "detect", "keymap", "history", "plan", "execute", "setTime", "restorePlan", "saveWorkspace", "testAIConnection", "generateAI", "prepareAIImages"))
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--resource-dir", required=True)
    args = parser.parse_args()
    try:
        max_input = MAX_WORKSPACE_BYTES if args.action == "saveWorkspace" else MAX_INPUT_BYTES
        raw = sys.stdin.buffer.read(max_input + 1)
        require(len(raw) <= max_input, "input_too_large", "输入文件过大。")
        payload = json.loads(raw or b"{}")
        require(isinstance(payload, dict), "invalid_input", "输入需要是 JSON 对象。")
        bridge = Bridge(args.state_dir, args.resource_dir)
        # Native serializes actions; the lock also prevents a second app process
        # from interleaving a plan or write with this one.
        if args.action in ("plan", "execute", "setTime", "restorePlan", "detect", "keymap"):
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
