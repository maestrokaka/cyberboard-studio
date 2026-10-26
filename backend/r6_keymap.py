"""R6 scoped key/macro/tap-hold commands, independently encoded from wire facts.

No JSON_START/END or LED command is emitted here. All mutating operations use a
single-use reviewed plan bound to an exact identity and a fresh key snapshot.
The caller holds the shared device-operation lock. No USB is used on import.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

CODE = re.compile(r"^#[0-9a-fA-F]{8}$")
TOKEN = re.compile(r"^[0-9a-f]{32}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
ZERO = "#00000000"
MAX_MACROS, MAX_EVENTS, MAX_HOLDS = 32, 200, 200
PLAN_SECONDS = 1800


class R6KeymapError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def require(condition, code, message, **details):
    if not condition:
        raise R6KeymapError(code, message, **details)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_json(path):
    path = Path(path)
    require(path.is_file() and path.stat().st_size <= 2 * 1024 * 1024,
            "r6_plan_missing", "键位计划或备份已不存在，请重新读取设备。")
    return json.loads(path.read_text())


def crc8(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ (7 if crc & 128 else 0)) & 255
    return crc


def frame(subcommand, payload=b""):
    require(len(payload) <= 61, "r6_frame_invalid", "指令内容超过一包。")
    data = (bytes([6, subcommand]) + bytes(payload)).ljust(63, b"\0")
    return data + bytes([crc8(data)])


def code_bytes(code):
    require(isinstance(code, str) and CODE.fullmatch(code), "r6_code_invalid", "键码必须为完整的四字节十六进制编码。")
    return bytes.fromhex(code[1:])


def read_code(data, index):
    return "#" + data[index:index + 4].hex().upper()


def matrix_bytes(keymap):
    layers = keymap.get("layer_data") if isinstance(keymap, dict) else None
    require(isinstance(layers, list) and len(layers) == 7 and
            all(isinstance(row, dict) and isinstance(row.get("layer"), list) and len(row["layer"]) == 200 for row in layers),
            "r6_keymap_incomplete", "需要完整七层、1400 个键码。")
    return b"".join(code_bytes(code) for row in layers for code in row["layer"])


def keymap_hash(keymap):
    return hashlib.sha256(matrix_bytes(keymap)).hexdigest()


def is_r6(identity):
    return str(identity.product_id or "").upper() in ("AM01R6", "CB06", "CB_06", "CBR6", "CB_R6")


def change_key(layer, index, before, after):
    require(type(layer) is int and 0 <= layer < 7 and type(index) is int and 0 <= index < 200,
            "r6_key_position_invalid", "按键位置或功能层无效。")
    return frame(0x0B, bytes([layer, index // 25, index % 25]) + code_bytes(before) + code_bytes(after))


def press_hold_packet(item):
    trigger = code_bytes(item["trigger"])
    require(trigger[:3] == bytes.fromhex("009514") and trigger[3] < MAX_HOLDS,
            "r6_hold_trigger_invalid", "长短按触发编号无效。")
    interval = item["intervalMs"]
    require(type(interval) is int and 0 <= interval <= 15000, "r6_interval_invalid", "长短按间隔超出范围。")
    payload = bytes([0, 200, 0, trigger[3]]) + trigger + interval.to_bytes(2, "big")
    return frame(0x0D, payload + code_bytes(item["tapCode"]) + code_bytes(item["holdCode"]))


def macro_packets(items):
    chunks = []
    for item in items:
        trigger = code_bytes(item["trigger"])
        require(trigger[:3] == bytes.fromhex("009515") and trigger[3] < MAX_MACROS,
                "r6_macro_trigger_invalid", "宏编号超出 32 个槽位。")
        events = item["events"]
        for local, offset in enumerate(range(0, max(1, len(events)), 8)):
            chunks.append((trigger, local, events[offset:offset + 8]))
    require(len(chunks) <= 255, "r6_macro_limit", "宏分包数量超过协议上限。")
    packets = []
    for index, (trigger, local, events) in enumerate(chunks):
        payload = bytes([len(chunks), index, trigger[3]]) + trigger + bytes([local])
        for event in events:
            delay = event["delayMs"]
            # Existing device records may use a zero/default or a wider u16
            # interval. Preserve them; the editor limits new input separately.
            require(type(delay) is int and 0 <= delay <= 65535, "r6_interval_invalid", "宏间隔超出协议范围。")
            payload += code_bytes(event["code"]) + delay.to_bytes(2, "big")
        packets.append(frame(0x05, payload))
    return packets


def _validate_frames(frames, subcommand, *, press_hold=False):
    require(frames and len(frames) <= 255, "r6_read_incomplete", "设备没有返回完整的高级键位表。")
    for packet in frames:
        require(len(packet) == 64 and packet[:2] == bytes([6, subcommand]) and crc8(packet[:63]) == packet[63],
                "r6_read_invalid", "高级键位回读包格式或校验不正确。")
    counts = {int.from_bytes(packet[2:4], "big") if press_hold else packet[2] for packet in frames}
    require(len(counts) == 1, "r6_read_incomplete", "高级键位回读包总数不一致。")
    total = counts.pop()
    if total == 0:
        require(len(frames) == 1 and not any(frames[0][2:63]), "r6_read_incomplete", "无法确认空高级键位表。")
        return []
    require(total == len(frames), "r6_read_incomplete", "高级键位回读缺少分包。")
    indexes = [packet[5] if press_hold else packet[3] for packet in frames]
    require(len(set(indexes)) == len(indexes), "r6_read_incomplete", "高级键位回读出现重复分包。")
    if not press_hold:
        require(sorted(indexes) == list(range(total)), "r6_read_incomplete", "宏回读分包编号不连续。")
    return sorted(frames, key=lambda packet: packet[5] if press_hold else packet[3])


def parse_macros(frames):
    groups = {}
    for packet in _validate_frames(frames, 0x0A):
        trigger = read_code(packet, 5)
        require(trigger.startswith("#009515") and int(trigger[-2:], 16) == packet[4] and packet[4] < MAX_MACROS,
                "r6_read_unsupported", "设备宏触发码无法安全解释，已停止高级功能编辑。")
        item = groups.setdefault(trigger, {})
        require(packet[9] not in item, "r6_read_incomplete", "宏内部存在重复分包。")
        events = []
        padded = False
        for offset in range(10, 58, 6):
            code, delay = read_code(packet, offset), int.from_bytes(packet[offset + 4:offset + 6], "big")
            if code == ZERO:
                require(delay == 0, "r6_read_unsupported", "宏占位事件含未知延时。")
                padded = True
            else:
                require(not padded and 0 <= delay <= 65535, "r6_read_incomplete", "宏事件中间存在未知空洞。")
                events.append({"code": code, "delayMs": delay})
        require(not any(packet[58:63]), "r6_read_unsupported", "宏保留字节含未解释数据。")
        item[packet[9]] = events
    result = []
    for trigger, parts in sorted(groups.items()):
        require(sorted(parts) == list(range(len(parts))), "r6_read_incomplete", "宏内部缺少分包。")
        events = [event for index in sorted(parts) for event in parts[index]]
        if events:
            result.append({"trigger": trigger, "events": events})
    require(sum(len(item["events"]) for item in result) <= MAX_EVENTS, "r6_read_unsupported", "设备宏超过当前已验证的事件上限。")
    return result


def parse_press_holds(frames):
    result, seen = [], set()
    for packet in _validate_frames(frames, 0x0E, press_hold=True):
        trigger = read_code(packet, 6)
        require(trigger.startswith("#009514") and int(trigger[-2:], 16) < MAX_HOLDS,
                "r6_read_unsupported", "设备长短按触发码无法安全解释。")
        require(trigger not in seen, "r6_read_incomplete", "长短按表包含重复触发码。")
        seen.add(trigger)
        require(not any(packet[20:63]), "r6_read_unsupported", "长短按保留字节含未解释数据。")
        item = {"trigger": trigger, "intervalMs": int.from_bytes(packet[10:12], "big"),
                "tapCode": read_code(packet, 12), "holdCode": read_code(packet, 16)}
        if item["tapCode"] != ZERO or item["holdCode"] != ZERO or item["intervalMs"]:
            result.append(item)
    return sorted(result, key=lambda item: item["trigger"])


def _open(bridge, port):
    return bridge.cli["cb_write"].serial.Serial(port, baudrate=9600, timeout=1.5, write_timeout=2, exclusive=True)


def _read_legacy(bridge, port, subcommand):
    ser = _open(bridge, port)
    try:
        time.sleep(0.1)
        ser.reset_input_buffer()
        require(ser.write(frame(subcommand, b"\0")) == 64, "r6_short_read_request", "高级键位查询发送不完整。")
        ser.flush()
        packets, expected, deadline = [], None, time.monotonic() + 10
        while time.monotonic() < deadline and len(packets) < 255:
            data = ser.read(64)
            if not data:
                break
            require(len(data) == 64 and crc8(data[:63]) == data[63], "r6_read_invalid", "高级键位回读校验失败。")
            if data[:2] != bytes([6, subcommand]):
                continue
            packets.append(data)
            expected = int.from_bytes(data[2:4], "big") if subcommand == 0x0E else data[2]
            if expected == 0 or len(packets) >= expected:
                break
        parser = parse_macros if subcommand == 0x0A else parse_press_holds
        return parser(packets), b"".join(packets)
    finally:
        ser.close()


def _snapshot(bridge, identity):
    keymap, raw = bridge.read_live(identity.port)
    result = {"keymap": keymap, "keymapHash": keymap_hash(keymap), "advanced": None,
              "advancedError": None, "rawKeymapHash": hashlib.sha256(raw).hexdigest()}
    try:
        macros, macro_raw = _read_legacy(bridge, identity.port, 0x0A)
        holds, hold_raw = _read_legacy(bridge, identity.port, 0x0E)
        advanced = {"macros": macros, "pressHolds": holds}
        result.update(advanced=advanced, advancedHash=digest(advanced),
                      rawAdvancedHash=hashlib.sha256(macro_raw + hold_raw).hexdigest(),
                      rawMacroHex=macro_raw.hex(), rawPressHoldHex=hold_raw.hex())
    except (R6KeymapError, OSError) as error:
        result["advancedError"] = str(error)[:500]
    return result, raw


def _directory(bridge):
    return bridge.state_dir / "r6-keymap-plans"


def _state_path(bridge, product_id):
    return bridge.state_dir / "r6-keymap-state" / (hashlib.sha256(str(product_id).encode()).hexdigest() + ".json")


def _record_advanced(bridge, identity, advanced=None, *, unknown=False):
    value = {"productId": identity.product_id, "firmware": identity.version, "recordedTimestamp": time.time(),
             "known": not unknown and advanced is not None,
             "active": None if unknown or advanced is None else bool(advanced["macros"] or advanced["pressHolds"])}
    if advanced is not None and not unknown:
        value.update(advanced=copy.deepcopy(advanced), snapshotHash=digest(advanced))
    atomic_json(_state_path(bridge, identity.product_id), value)
    return value


def inspect_advanced_protection(bridge, identity, *, refresh=True):
    """Full-JSON callers must not erase active OR unreadable advanced tables.

    Query both tables, even when no trigger is presently mapped in the matrix:
    unbound macros still exist and must survive. A cache is labelled stale and
    never replaces the refresh required before destructive full-config writes.
    """
    if not is_r6(identity):
        return {"known": False, "active": None, "applicable": False, "source": "not-r6"}
    if not refresh:
        location = _state_path(bridge, identity.product_id)
        return {**(load_json(location) if location.exists() else {"known": False, "active": None}), "applicable": True, "source": "local-stale"}
    try:
        macros, _ = _read_legacy(bridge, identity.port, 0x0A)
        holds, _ = _read_legacy(bridge, identity.port, 0x0E)
        advanced = {"macros": macros, "pressHolds": holds}
        value = _record_advanced(bridge, identity, advanced)
        return {**value, "applicable": True, "source": "live-readback"}
    except (R6KeymapError, OSError) as error:
        # Keep a known-active prior record, but do not label it current.
        previous = inspect_advanced_protection(bridge, identity, refresh=False)
        return {"known": False, "active": previous.get("active"), "applicable": True,
                "source": "readback-unavailable", "reason": str(error)[:500]}


def _identity(bridge, payload):
    identity = bridge.discover({"port": payload["port"]} if payload.get("port") else {})
    require(identity is not None and is_r6(identity), "r6_device_required", "这个独立指令编辑器需要通过 USB 连接 R6。")
    require(identity.version, "r6_firmware_unknown", "固件版本未读取完整，请重新检测。")
    return identity


def _device_match(identity, metadata):
    return identity.product_id == metadata.get("productId") and identity.version == metadata.get("firmware") and identity.port == metadata.get("port")


def _pending_unknown(bridge, product_id):
    result = []
    for path in sorted(_directory(bridge).glob("*/plan.json")):
        data = load_json(path)
        if data.get("productId") == product_id and data.get("deviceMayHaveChanged") is True and data.get("status") in ("executing", "unknown"):
            result.append((path, data))
    return result


def read(bridge, payload):
    identity = _identity(bridge, payload)
    snapshot, _ = _snapshot(bridge, identity)
    if snapshot["advanced"] is not None:
        _record_advanced(bridge, identity, snapshot["advanced"])
    for path, plan in _pending_unknown(bridge, identity.product_id):
        # A key-only operation never emitted a table command. A fresh complete
        # matrix is sufficient to resume key-only work when that firmware does
        # not expose advanced reads. Advanced/full-JSON work remains blocked.
        key_only = plan.get("edit") is None
        if snapshot["advanced"] is not None or key_only:
            plan.update(status="resolved", resolution="fresh-complete-readback", resolvedSnapshotHash=digest(snapshot))
            if snapshot["advanced"] is None:
                plan["resolution"] = "fresh-complete-keymap-only-readback"
            atomic_json(path, plan)
    advanced = {"source": "live", "available": snapshot["advanced"] is not None,
                "verification": "readback-verified" if snapshot["advanced"] is not None else "unavailable",
                "snapshotHash": snapshot.get("advancedHash"), "reason": snapshot.get("advancedError")}
    if snapshot["advanced"] is not None:
        advanced.update(copy.deepcopy(snapshot["advanced"]))
    return {"connected": True, "device": bridge.device_dict(identity), "keymap": bridge.keymap_view(snapshot["keymap"]),
            "advanced": advanced, "directKeymapSupported": True}


def _changes(bridge, snapshot, payload):
    changes = bridge.validated_key_changes(payload.get("keyChanges", []), allow_empty=True)
    target = copy.deepcopy(snapshot)
    for item in changes:
        old = target["keymap"]["layer_data"][item["layer"]]["layer"][item["matrixIndex"]]
        require(not item["code"].upper().startswith(("#009514", "#009515")), "r6_advanced_binding_required",
                "长短按和宏触发码需要由专门编辑器创建并核对。")
        target["keymap"]["layer_data"][item["layer"]]["layer"][item["matrixIndex"]] = item["code"]
    return target


def _edit_advanced(bridge, snapshot, target, edit):
    require(snapshot["advanced"] is not None, "r6_advanced_unavailable", "高级键位表未完整读取，不能创建或修改长短按和宏。")
    require(isinstance(edit, dict) and edit.get("type") in ("macro", "press-hold", "remove-macro", "remove-press-hold"),
            "r6_edit_invalid", "高级键位操作无效。")
    common = {"type", "layer", "matrixIndex"}
    kind = edit["type"]
    fields = common | ({"events"} if kind == "macro" else {"tapCode", "holdCode", "intervalMs"} if kind == "press-hold" else {"replacementCode"})
    require(set(edit) == fields, "r6_edit_invalid", "高级键位操作包含缺少或额外字段。")
    # Reuse the same physical position policy as ordinary edits.
    bridge.validated_key_changes([{"layer": edit["layer"], "matrixIndex": edit["matrixIndex"], "code": ZERO}])
    layer, index = edit["layer"], edit["matrixIndex"]
    old = target["keymap"]["layer_data"][layer]["layer"][index].upper()
    table_name = "macros" if "macro" in kind else "pressHolds"
    prefix, limit = ("#009515", MAX_MACROS) if table_name == "macros" else ("#009514", MAX_HOLDS)
    table = target["advanced"][table_name]
    existing = next((item for item in table if item["trigger"] == old), None)
    if kind.startswith("remove-"):
        require(existing is not None, "r6_edit_missing", "选中的实体键没有对应的高级功能。")
        # Deleting a shared trigger must not silently change other bindings.
        references = [(a, b) for a, row in enumerate(target["keymap"]["layer_data"]) for b, code in enumerate(row["layer"]) if code.upper() == old]
        require(references == [(layer, index)], "r6_shared_trigger", "该功能被多个键引用，请先将其他引用改为普通按键。")
        replacement = edit["replacementCode"]
        code_bytes(replacement)
        require(not replacement.upper().startswith(("#009514", "#009515")), "r6_edit_invalid", "删除功能后请选择普通按键。")
        target["advanced"][table_name] = [item for item in table if item["trigger"] != old]
        target["keymap"]["layer_data"][layer]["layer"][index] = replacement
        return
    if existing:
        references = [(a, b) for a, row in enumerate(target["keymap"]["layer_data"]) for b, code in enumerate(row["layer"]) if code.upper() == old]
        require(references == [(layer, index)], "r6_shared_trigger", "该功能被多个键引用，请先拆分引用后编辑。")
        trigger = old
    else:
        used = {item["trigger"] for item in table}
        used.update(code.upper() for row in target["keymap"]["layer_data"] for code in row["layer"])
        trigger = next((prefix + f"{number:02X}" for number in range(limit) if prefix + f"{number:02X}" not in used), None)
        require(trigger is not None, "r6_advanced_limit", "高级功能编号已用完，请先删除不用的功能。")
    if kind == "macro":
        events = edit["events"]
        require(isinstance(events, list) and 1 <= len(events) <= MAX_EVENTS, "r6_macro_limit", "宏需要 1–200 个按下或松开事件。")
        held = set()
        for event in events:
            require(isinstance(event, dict) and set(event) == {"code", "delayMs"}, "r6_edit_invalid", "宏事件格式无效。")
            data = code_bytes(event["code"])
            require(data[0] in (0x10, 0x11) and data[1] in (0x07, 0x0C), "r6_macro_event_invalid", "宏事件需要使用按下或松开的普通键／媒体键编码。")
            key = data[1:]
            if data[0] == 0x11:
                require(key not in held, "r6_macro_unbalanced", "宏中同一按键连续按下而没有松开。")
                held.add(key)
            else:
                require(key in held, "r6_macro_unbalanced", "宏中存在没有对应按下的松开事件。")
                held.remove(key)
            require(type(event["delayMs"]) is int and 1 <= event["delayMs"] <= 15000, "r6_interval_invalid", "宏事件间隔需为 1–15000 ms。")
        require(not held, "r6_macro_unbalanced", "宏结束前必须松开所有按键。")
        item = {"trigger": trigger, "events": copy.deepcopy(events)}
    else:
        for field in ("tapCode", "holdCode"):
            code_bytes(edit[field])
            require(edit[field] != ZERO and not edit[field].upper().startswith(("#009514", "#009515")), "r6_edit_invalid", "点击和长按需要选择普通功能，不能递归调用高级触发码。")
        require(type(edit["intervalMs"]) is int and 10 <= edit["intervalMs"] <= 15000, "r6_interval_invalid", "长短按间隔需为 10–15000 ms。")
        item = {"trigger": trigger, "tapCode": edit["tapCode"], "holdCode": edit["holdCode"], "intervalMs": edit["intervalMs"]}
    table = [entry for entry in table if entry["trigger"] != trigger] + [item]
    target["advanced"][table_name] = sorted(table, key=lambda entry: entry["trigger"])
    require(sum(len(entry["events"]) for entry in target["advanced"]["macros"]) <= MAX_EVENTS, "r6_macro_limit", "所有宏合计最多 200 个事件。")
    target["keymap"]["layer_data"][layer]["layer"][index] = trigger


def wire_plan(before, target):
    packets = []
    if before["advanced"] is not None and target["advanced"] is not None:
        old, new = before["advanced"], target["advanced"]
        # The website sends the complete macro table plus explicit tombstones,
        # not an assumed single-slot update. Keep every non-target event.
        macros = copy.deepcopy(new["macros"]) if new["macros"] != old["macros"] else []
        macros += [{"trigger": entry["trigger"], "events": []} for entry in old["macros"] if not any(item["trigger"] == entry["trigger"] for item in new["macros"])]
        packets.extend(macro_packets(macros))
        holds = [entry for entry in new["pressHolds"] if entry not in old["pressHolds"]]
        holds += [{"trigger": entry["trigger"], "tapCode": ZERO, "holdCode": ZERO, "intervalMs": 0} for entry in old["pressHolds"] if not any(item["trigger"] == entry["trigger"] for item in new["pressHolds"])]
        packets.extend(press_hold_packet(item) for item in holds)
    for layer in range(7):
        for index in range(200):
            old, new = before["keymap"]["layer_data"][layer]["layer"][index], target["keymap"]["layer_data"][layer]["layer"][index]
            if old.upper() != new.upper():
                packets.append(change_key(layer, index, old, new))
    return packets


def _snapshot_core(snapshot):
    return {"keymapHash": keymap_hash(snapshot["keymap"]), "advanced": snapshot["advanced"]}


def plan(bridge, payload):
    require(isinstance(payload, dict) and set(payload) <= {"expectedKeymapHash", "expectedAdvancedHash", "expectedProductId", "expectedFirmware", "keyChanges", "edit", "port"},
            "r6_plan_invalid", "键位计划不能混入灯效或其他设置。")
    require(isinstance(payload.get("expectedKeymapHash"), str) and HASH.fullmatch(payload["expectedKeymapHash"]), "r6_snapshot_required", "请先读取完整键位。")
    identity = _identity(bridge, payload)
    require(identity.product_id == payload.get("expectedProductId") and identity.version == payload.get("expectedFirmware"), "r6_device_changed", "当前设备或固件与编辑基底不同。")
    require(not _pending_unknown(bridge, identity.product_id), "r6_state_unknown", "上一次独立键位写入结果未知，请先点击读取设备，完整确认后再准备。")
    before, raw = _snapshot(bridge, identity)
    require(before["keymapHash"] == payload["expectedKeymapHash"], "r6_keymap_changed", "设备键位与草稿基底不同，请重新读取并核对。")
    target = _changes(bridge, before, payload)
    if "edit" in payload:
        require(not payload.get("keyChanges"), "r6_plan_invalid", "一次只审核普通改键或一项高级功能。")
        require(before.get("advancedHash") == payload.get("expectedAdvancedHash") and before["advanced"] is not None, "r6_advanced_changed", "高级键位表与编辑基底不同，请重新读取。")
        _edit_advanced(bridge, before, target, payload["edit"])
    packets = wire_plan(before, target)
    require(packets, "r6_no_changes", "设备配置没有实际变化，未创建写入计划。")
    token, created = uuid.uuid4().hex, time.time()
    folder = _directory(bridge) / token
    backup = {"device": bridge.device_dict(identity), "snapshot": before, "rawKeymapHex": raw.hex()}
    atomic_json(folder / "before.json", backup)
    atomic_json(folder / "target.json", target)
    metadata = {"schemaVersion": 1, "kind": "r6-keymap-direct", "token": token, "createdTimestamp": created,
                "productId": identity.product_id, "firmware": identity.version, "port": identity.port,
                "beforeHash": digest(backup), "targetHash": digest(target), "frameHash": hashlib.sha256(b"".join(packets)).hexdigest(),
                "status": "prepared", "transferState": "not-started", "deviceMayHaveChanged": False,
                "edit": copy.deepcopy(payload.get("edit")), "keyChanges": copy.deepcopy(payload.get("keyChanges", []))}
    atomic_json(folder / "plan.json", metadata)
    summary = []
    for layer in range(7):
        for index in range(200):
            old, new = before["keymap"]["layer_data"][layer]["layer"][index], target["keymap"]["layer_data"][layer]["layer"][index]
            if old.upper() != new.upper():
                summary.append({"layer": layer, "matrixIndex": index, "before": bridge.decode_binding(old), "after": bridge.decode_binding(new)})
    return {"kind": "keymap", "mode": "r6-direct", "token": token, "expectedKeymapHash": before["keymapHash"],
            "device": bridge.device_dict(identity), "keyChanges": summary, "keyChangeCount": len(summary),
            "targetKeymap": bridge.keymap_view(target["keymap"], source="prepared"), "changedSlots": [], "summary": [],
            "advancedEdit": copy.deepcopy(payload.get("edit")), "advancedBefore": before["advanced"], "advancedTarget": target["advanced"],
            "totalFrames": len(packets), "estimatedSeconds": max(3, len(packets) * .005 + 8),
            "backupPath": str(folder / "before.json"), "ledTransmitted": False, "requiresDeviceAck": False,
            "verification": {"keymap": "pending", "advanced": "pending" if before["advanced"] is not None else "unavailable", "led": "not-transmitted"}}


def execute(bridge, payload):
    require(isinstance(payload, dict) and set(payload) == {"token"} and isinstance(payload["token"], str) and TOKEN.fullmatch(payload["token"]), "r6_plan_invalid", "请选择有效的独立键位计划。")
    folder = _directory(bridge) / payload["token"]
    metadata, backup, target = load_json(folder / "plan.json"), load_json(folder / "before.json"), load_json(folder / "target.json")
    require(metadata.get("schemaVersion") == 1 and metadata.get("kind") == "r6-keymap-direct" and metadata.get("token") == payload["token"] and metadata.get("status") == "prepared" and
            type(metadata.get("createdTimestamp")) in (int, float) and 0 <= time.time() - metadata["createdTimestamp"] <= PLAN_SECONDS,
            "r6_plan_expired", "计划已执行、失效或过期，请重新读取并审核。")
    require(metadata["beforeHash"] == digest(backup) and metadata["targetHash"] == digest(target), "r6_plan_tampered", "键位计划或备份发生变化。")
    before = backup["snapshot"]
    packets = wire_plan(before, target)
    require(packets and hashlib.sha256(b"".join(packets)).hexdigest() == metadata["frameHash"], "r6_plan_tampered", "独立指令与审核计划不同。")
    require(all(packet[0] == 6 and packet[1] in (5, 11, 13) for packet in packets), "r6_plan_tampered", "计划包含不允许的指令。")
    identity = _identity(bridge, {"port": metadata["port"]})
    require(_device_match(identity, metadata), "r6_device_changed", "USB 设备或固件已变化。")
    require(not _pending_unknown(bridge, identity.product_id), "r6_state_unknown", "其他独立键位计划的设备结果未知，请先明确重新读取。")
    actual, _ = _snapshot(bridge, identity)
    require(_snapshot_core(actual) == _snapshot_core(before), "r6_keymap_changed", "设备键位或高级表已变化，计划未执行。")
    ser, sent = None, 0
    try:
        ser = _open(bridge, identity.port)
        time.sleep(.1)
        ser.reset_input_buffer()
        metadata.update(status="executing", transferState="started", deviceMayHaveChanged=True, startedTimestamp=time.time())
        atomic_json(folder / "plan.json", metadata)
        _record_advanced(bridge, identity, unknown=True)
        for index, packet in enumerate(packets):
            require(ser.write(packet) == 64, "r6_short_write", "独立键位指令发送中断。", deviceMayHaveChanged=True)
            sent = index + 1
            bridge.event("sending", sent, len(packets))
            time.sleep(.005)
        ser.flush()
        metadata.update(transferState="sent", sentFrames=sent)
        atomic_json(folder / "plan.json", metadata)
        ser.close()
        ser = None
        time.sleep(.25)
        bridge.event("verifying", sent, len(packets))
        after, _ = _snapshot(bridge, identity)
        require(matrix_bytes(after["keymap"]) == matrix_bytes(target["keymap"]), "r6_keymap_unverified", "指令已发送，但完整键位回读不一致。", deviceMayHaveChanged=True)
        if before["advanced"] is not None:
            require(after["advanced"] == target["advanced"], "r6_advanced_unverified", "指令已发送，但高级功能表回读未完成或不一致。", deviceMayHaveChanged=True)
        verification = {"keymap": "readback-verified", "advanced": "readback-verified" if before["advanced"] is not None else "unavailable", "led": "not-transmitted"}
        result = {"success": True, "status": "verified", "transferState": "sent", "deviceMayHaveChanged": True,
                  "deviceAck": None, "keymapMatch": True, "keymap": {**bridge.keymap_view(after["keymap"]), "verifiedReadback": True},
                  "advanced": {**(copy.deepcopy(after["advanced"]) or {}), "available": after["advanced"] is not None, "snapshotHash": after.get("advancedHash"), "source": "live"},
                  "device": bridge.device_dict(identity), "verification": verification, "backupPath": str(folder / "before.json"),
                  "stateStored": True, "reportStored": True, "ledTransmitted": False, "totalFrames": len(packets)}
        metadata.update(status="complete", verification=verification, completedTimestamp=time.time())
        _record_advanced(bridge, identity, after["advanced"], unknown=after["advanced"] is None)
        atomic_json(folder / "result.json", result)
        atomic_json(folder / "plan.json", metadata)
        return result
    except Exception as error:
        if metadata.get("deviceMayHaveChanged") is True:
            metadata.update(status="unknown", transferState="sent" if sent == len(packets) else "started", sentFrames=sent,
                            verification={"keymap": "unknown", "advanced": "unknown", "led": "not-transmitted"})
            atomic_json(folder / "plan.json", metadata)
            raise R6KeymapError("r6_state_unknown", "独立指令可能已经到达设备，结果尚未验证。请先重新读取设备，草稿和备份保留。",
                                deviceMayHaveChanged=True, sentFrames=sent, reason=str(error)[:500]) from error
        raise
    finally:
        if ser is not None:
            ser.close()


def dispatch(bridge, action, payload):
    return {"r6KeymapRead": read, "r6KeymapPlan": plan, "r6KeymapExecute": execute}[action](bridge, payload)
