"""Preview-only R6 scoped lighting protocol research.

This module has no transport, execute, serial, or bridge action. It validates
the *local* before/target scope and independently encodes an observed scoped
candidate. Firmware preservation is NOT established by these bytes or by an
ACK. The website's R6 full-profile compiler can normalize valid=2 back to 1;
never pass this preview profile into the ordinary full-configuration writer.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

SOURCE = "https://diy.angrymiao.com/js/chunk-02ab7e94.fc907547.js"
SOURCE_SHA256 = "924b2ad299ddffb87dad92018b53fdf2f2613e9b5375552a3c3a3d666cadeffa"
DOMAINS = {"top": ("frames", 200, 4), "keys": ("keyframes", 90, 5)}
RESERVED_AXIS = (57, 61, 74, 78, 82, 83, 84)
RGB = re.compile(r"^#[0-9a-fA-F]{6}$")
KEY = re.compile(r"^#[0-9a-fA-F]{8}$")


class PartialLightingError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PartialLightingError(message)


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise PartialLightingError("配置包含非 JSON 值。") from error


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _crc8(data):
    result = 0
    for byte in data:
        result ^= byte
        for _ in range(8):
            result = ((result << 1) ^ (7 if result & 128 else 0)) & 255
    return result


def _frame(command, subcommand, payload=b""):
    require(len(payload) <= 61, "候选协议包超过 64 字节。")
    data = (bytes([command, subcommand]) + payload).ljust(63, b"\0")
    return data + bytes([_crc8(data)])


def _flag(value):
    require(type(value) in (int, bool) and value in (0, 1), "完整配置的灯域启用标记必须为 0 或 1，不能预先混入忽略标记。")
    return int(value)


def _validate_group(group, count):
    require(isinstance(group, dict) and set(group) <= {"//", "valid", "frame_num", "frame_data"} and {"valid", "frame_num", "frame_data"} <= set(group), "灯域结构含缺少或未知字段。")
    _flag(group["valid"])
    number, data = group["frame_num"], group["frame_data"]
    require(type(number) is int and 0 <= number <= 255 and isinstance(data, list), "灯域帧数无效。")
    require(len(data) == number or (number == 0 and len(data) <= 1), "灯域帧数和数据长度不一致。")
    for index, item in enumerate(data):
        require(isinstance(item, dict) and set(item) <= {"//", "frame_index", "frame_RGB"} and item.get("frame_index") == index and type(item.get("frame_index")) is int, "灯域帧编号或字段无效。")
        colors = item.get("frame_RGB")
        inactive_placeholder = group["valid"] == 0 and number == 0 and isinstance(colors, list) and len(colors) == 1
        require(isinstance(colors, list) and (len(colors) == count or inactive_placeholder) and all(isinstance(color, str) and RGB.fullmatch(color) for color in colors), "启用的灯域必须包含完整的 200 顶灯或 90 轴灯 RGB。")
        if count == 90 and not inactive_placeholder:
            require(all(colors[position].upper() == "#000000" for position in RESERVED_AXIS), "七个无效轴灯位置必须保持黑色。")


def _validate_config(config):
    require(isinstance(config, dict) and type(config.get("page_num")) is int and config["page_num"] == 8,
            "当前候选仅支持完整的 R6 八页面配置。")
    pages = config.get("page_data")
    require(isinstance(pages, list) and len(pages) == 8 and all(isinstance(page, dict) and type(page.get("page_index")) is int and page["page_index"] == index for index, page in enumerate(pages)), "页面编号必须连续为 0–7。")
    require(isinstance(config.get("key_layer"), dict) and type(config["key_layer"].get("layer_num")) is int and config["key_layer"]["layer_num"] == 7, "键层数量必须为七层。")
    layers = config["key_layer"].get("layer_data")
    require(isinstance(layers, list) and len(layers) == 7 and all(isinstance(row, dict) and isinstance(row.get("layer"), list) and len(row["layer"]) == 200 and all(isinstance(code, str) and KEY.fullmatch(code) for code in row["layer"]) for row in layers), "必须提供完整的 1400 键码，不能以忽略标记代替原配置。")
    for page in pages:
        require(type(page.get("speed_ms")) is int and 0 <= page["speed_ms"] <= 65535, "页面时序无效。")
        require(type(page.get("lightness")) is int and 0 <= page["lightness"] <= 100, "页面亮度无效。")
        _flag(page.get("valid"))
        for _, (field, count, _) in DOMAINS.items():
            _validate_group(page.get(field), count)
    canonical(config)


def _scope(slots, domains):
    require(isinstance(slots, (list, tuple)) and slots and all(type(slot) is int and 1 <= slot <= 3 for slot in slots) and len(set(slots)) == len(slots), "请明确选择不重复的自定义槽位 1–3。")
    require(isinstance(domains, (list, tuple)) and domains and all(isinstance(domain, str) and domain in DOMAINS for domain in domains) and len(set(domains)) == len(domains), "请明确选择 top 和／或 keys 灯域。")
    return sorted(slots), sorted(domains)


def validate_scope(before, target, *, slots, domains):
    """Only explicitly selected frame groups may differ; timing never changes."""
    slots, domains = _scope(slots, domains)
    _validate_config(before)
    _validate_config(target)
    restored = copy.deepcopy(target)
    changes = []
    for slot in slots:
        page_index = slot + 4
        for domain in domains:
            field = DOMAINS[domain][0]
            old, new = before["page_data"][page_index][field], target["page_data"][page_index][field]
            if canonical(old) != canonical(new):
                changes.append({"slot": slot, "pageIndex": page_index, "domain": domain,
                                "beforeHash": digest(old), "targetHash": digest(new),
                                "beforeFrames": old["frame_num"], "targetFrames": new["frame_num"]})
            restored["page_data"][page_index][field] = copy.deepcopy(old)
    require(canonical(restored) == canonical(before), "目标配置包含范围外修改：键位、宏、长短按、其他页面、另一灯域、文字、亮度、时序与页面控制必须逐字保留。")
    require(changes, "指定灯域没有实际变化。")
    return {"slots": slots, "domains": domains, "changes": changes,
            "localScopeVerified": True, "deviceStateVerified": False,
            "beforeHash": digest(before), "targetHash": digest(target),
            "preservedTiming": [page["speed_ms"] for page in before["page_data"]]}


def _profile(target, slots, domains):
    profile = copy.deepcopy(target)
    pages = {slot + 4 for slot in slots}
    for page in profile["page_data"]:
        selected = page["page_index"] in pages
        page["valid"] = 2
        # Every unsupported/non-target stream is an explicit ignore candidate.
        for name, (field, _, _) in DOMAINS.items():
            if not (selected and name in domains):
                page[field] = {"valid": 2, "frame_num": 0, "frame_data": []}
        page["word_page"] = {"valid": 2, "word_len": 0, "unicode": []}
        if "spotlight_frames" in page:
            page["spotlight_frames"] = {"valid": 2, "frame_num": 0, "frame_data": []}
        if "page_control" in page:
            page["page_control"]["valid"] = 2
    profile["key_layer"]["valid"] = 2
    return profile


def _encode(profile):
    # Observed E(): page control, text, top RGB, axis RGB for each page, then
    # key-layer flag. Only the selected RGB group is permitted to use 0 or 1.
    flags = []
    for page in profile["page_data"]:
        flags.extend([2, 2, int(page["frames"]["valid"]), int(page["keyframes"]["valid"])])
    flags.append(2)
    valid_packet = _frame(2, 5, bytes([8] + flags))
    # Observed A(): each page uses index, word length, top and axis frame counts;
    # both counts are little endian. No page-control or key-function frames.
    inventory = bytearray([8])
    for page in profile["page_data"]:
        inventory += bytes([page["page_index"], 0])
        for field in ("frames", "keyframes"):
            group = page[field]
            count = group["frame_num"] if group["valid"] == 1 else 0
            inventory += count.to_bytes(2, "little")
    payload = [_frame(2, 1, bytes(inventory))]
    for field, count, command in DOMAINS.values():
        for page in profile["page_data"]:
            group = page[field]
            if group["valid"] != 1:
                continue
            for item in group["frame_data"]:
                rgb = b"".join(bytes.fromhex(color[1:]) for color in item["frame_RGB"])
                for chunk in range(11 if count == 200 else 5):
                    header = item["frame_index"].to_bytes(2, "little") if command == 4 else bytes([item["frame_index"]])
                    payload.append(_frame(command, page["page_index"], header + bytes([chunk]) + rgb[56 * chunk:min(len(rgb), 56 * (chunk + 1))]))
    return valid_packet, payload, flags


def preview_plan(before, target, *, slots, domains):
    """Return an explicitly non-executable local plan and synthetic wire bytes."""
    scope = validate_scope(before, target, slots=slots, domains=domains)
    profile = _profile(target, scope["slots"], scope["domains"])
    directive, payload, flags = _encode(profile)
    all_frames = [directive, _frame(1, 5), *payload, _frame(1, 6, len(payload).to_bytes(4, "big"))]
    require(all(len(data) == 64 and _crc8(data[:63]) == data[63] for data in all_frames), "候选协议编码校验失败。")
    require(not any(data[0] in (6, 7, 12) for data in all_frames), "候选计划包含范围外的键位、声音或车灯指令。")
    return {"schemaVersion": 1, "kind": "r6-partial-lighting-preview", "executable": False,
            "requiresHardwareValidation": True, "protocolVariant": "observed-scoped-candidate",
            "scope": scope, "profile": profile, "validDirectives": flags,
            "dataFrameCount": len(payload), "wireFrameCount": len(all_frames),
            "candidateFramesHex": [data.hex() for data in all_frames],
            "candidateFrameHash": hashlib.sha256(b"".join(all_frames)).hexdigest(),
            "source": {"url": SOURCE, "sha256": SOURCE_SHA256,
                       "methods": ["E(valid flags)", "A(frame inventory)", "D(top RGB)", "I(axis RGB)", "Ie(scoped profile)", "sendValidDirectivesNow"]},
            "unverified": ["R6 固件是否按 valid:2 保留非目标区域和高级功能表",
                           "JSON_START/END 后旧帧、文字、键位、宏和长短按的真实保留行为",
                           "官网 R6 fullJsonSupported 分支与本候选范围编译的差异",
                           "发送回执无法替代完整灯效回读或实机观察"],
            "integrationWarning": "禁止将此 profile 交给普通全量写入器；valid:2 可能被视为启用或归一化成 1。此模块没有执行入口。"}
