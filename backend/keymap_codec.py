"""Public, offline key labels; raw four-byte codes remain the source of truth.

Names reuse the bundled CLI's bijective vocabulary. Vendor labels describe the
CLI's curated manufacturer labels, not separately verified firmware behavior.
Unknown codes (including modifier-only unknown values) are never normalized.
"""
from __future__ import annotations

import re
from functools import lru_cache

_CODE = re.compile(r"^#[0-9a-fA-F]{8}$")
_CATEGORIES = (
    ("keyboard", "普通按键"), ("modifier", "修饰键"), ("media", "媒体与系统亮度"),
    ("layer", "层与 Fn"), ("display", "顶部灯屏"), ("backlight", "轴灯"),
    ("wireless", "无线连接"), ("system", "键盘功能"), ("unassigned", "未绑定"),
)
MODIFIERS = (
    (1, "lctrl", "Ctrl", "左 Ctrl"), (2, "lshift", "Shift", "左 Shift"),
    (4, "lalt", "Alt", "左 Alt / Option"), (8, "lgui", "Win", "左 Win / Command"),
    (16, "rctrl", "右Ctrl", "右 Ctrl"), (32, "rshift", "右Shift", "右 Shift"),
    (64, "ralt", "右Alt", "右 Alt / Option"), (128, "rgui", "右Win", "右 Win / Command"),
)
_KEY_LABELS = {
    "enter": ("Enter", "回车"), "esc": ("Esc", "Esc"), "backspace": ("退格", "退格"),
    "tab": ("Tab", "Tab"), "space": ("空格", "空格"), "minus": ("-", "减号 -"),
    "equal": ("=", "等号 ="), "lbracket": ("[", "左方括号 ["), "rbracket": ("]", "右方括号 ]"),
    "backslash": ("\\", "反斜杠 \\"), "semicolon": (";", "分号 ;"), "quote": ("'", "单引号 '"),
    "grave": ("`", "反引号 `"), "comma": (",", "逗号 ,"), "period": (".", "句点 ."),
    "slash": ("/", "斜杠 /"), "caps": ("大写", "Caps Lock · 大写锁定"),
    "printscreen": ("截屏", "Print Screen · 截屏"), "scrolllock": ("滚锁", "Scroll Lock · 滚动锁定"),
    "pause": ("暂停", "Pause · 暂停"), "insert": ("插入", "Insert · 插入"), "home": ("Home", "Home"),
    "pageup": ("上页", "Page Up · 上一页"), "delete": ("删除", "Delete · 删除"), "end": ("End", "End"),
    "pagedown": ("下页", "Page Down · 下一页"), "right": ("→", "向右"), "left": ("←", "向左"),
    "down": ("↓", "向下"), "up": ("↑", "向上"), "numlock": ("数锁", "Num Lock · 数字锁定"),
    "app": ("菜单", "应用菜单"), "next": ("下一首", "下一首"), "prev": ("上一首", "上一首"),
    "stop": ("停止", "停止播放"), "play": ("播放", "播放 / 暂停"), "mute": ("静音", "静音"),
    "volup": ("音量+", "增加音量"), "voldown": ("音量−", "降低音量"),
    "brightup": ("屏亮+", "增加系统屏幕亮度"), "brightdown": ("屏亮−", "降低系统屏幕亮度"),
}
_VENDOR_LABELS = {
    "NextLED": ("屏模式", "切换顶部灯屏模式", "display"),
    "LED_OnOff": ("屏开关", "顶部灯屏开关", "display"),
    "LED_Light+": ("屏亮+", "增加顶部灯屏亮度", "display"),
    "LED_Light-": ("屏亮−", "降低顶部灯屏亮度", "display"),
    "LED_Speed+": ("屏速+", "增加顶部灯屏速度", "display"),
    "LED_Speed-": ("屏速−", "降低顶部灯屏速度", "display"),
    "LED_Rotation": ("屏旋转", "顶部灯屏旋转", "display"),
    "2_4G": ("2.4G", "2.4 GHz 无线连接", "wireless"),
    "NextPCB": ("轴模式", "切换轴灯模式", "backlight"),
    "PCB_Light+": ("轴亮+", "增加轴灯亮度", "backlight"),
    "PCB_Light-": ("轴亮−", "降低轴灯亮度", "backlight"),
    "PCB_OnOff": ("轴开关", "轴灯开关", "backlight"),
    "PCB_Speed+": ("轴速+", "增加轴灯速度", "backlight"),
    "PCB_Speed-": ("轴速−", "降低轴灯速度", "backlight"),
    "PCB_SAT": ("轴饱和", "轴灯饱和度", "backlight"),
    "PCB_Light": ("轴亮度", "轴灯亮度", "backlight"),
    "LED_Color": ("轴颜色", "轴灯颜色", "backlight"),
    "Win_Mac": ("Win/Mac", "切换 Windows / macOS 模式", "system"),
    "Battery": ("电量", "查看电量", "system"), "Reset": ("重置", "重置键盘", "system"),
    "TouchSen": ("触控", "触控灵敏度", "system"),
}


def _named_labels(page, usage, token):
    if token.startswith("Layer"):
        number = token[5:]
        return f"层{number}", f"切换到层 {number}", "layer"
    if token.startswith("Fn"):
        number = token[2:]
        return f"Fn{number}", f"Fn {number} · 按住切换到层 {number}", "layer"
    if token.startswith("BT"):
        return token, f"蓝牙连接 {token[2:]}", "wireless"
    if token in _VENDOR_LABELS:
        return _VENDOR_LABELS[token]
    modifier = next((item for item in MODIFIERS if item[1] == token), None)
    if modifier:
        return modifier[2], modifier[3], "modifier"
    short, name = _KEY_LABELS.get(token, (token.upper(), token.upper()))
    return short, name, "media" if page == 0x0C else "keyboard"


@lru_cache(maxsize=1)
def _table():
    # load_cli() establishes the bundled tools path. No USB or store is used.
    from keycode import CODE_TO_NAME
    entries = [{"code": "#00000000", "token": ".", "short": "—", "name": "未绑定", "category": "unassigned"}]
    for (page, usage), token in CODE_TO_NAME.items():
        short, name, category = _named_labels(page, usage, token)
        entries.append({"code": f"#00{page:02X}{usage:04X}", "token": token,
                        "short": short, "name": name, "category": category})
    return {entry["code"]: entry for entry in entries}


def catalog():
    return {"schemaVersion": 1, "layerCount": 7, "physicalKeyCount": 81,
            "categories": [{"id": identity, "name": name} for identity, name in _CATEGORIES],
            "entries": [dict(entry) for entry in _table().values()],
            "modifiers": [{"mask": mask, "token": token, "short": short, "name": name}
                          for mask, token, short, name in MODIFIERS],
            "vendorLabelSource": "bundled-cli-labels", "vendorBehaviorVerified": False}


def decode(code):
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise ValueError("key code must use #MMPPUUUU")
    raw = code.upper()
    table = _table()
    if raw in table:
        return dict(table[raw])
    mask = int(raw[1:3], 16)
    base = table.get("#00" + raw[3:])
    # Only exact all-zero is unassigned. Preserve #MM000000 as an unknown code.
    if mask and base and base["category"] != "unassigned":
        mods = [item for item in MODIFIERS if mask & item[0]]
        return {"code": raw, "token": raw, "short": "+".join([item[2] for item in mods] + [base["short"]]),
                "name": " + ".join([item[3] for item in mods] + [base["name"]]),
                "category": "combination", "modifierMask": mask, "baseCode": base["code"]}
    return {"code": raw, "token": raw, "short": "自定义", "name": f"自定义功能 · {raw}",
            "category": "unknown", "modifierMask": mask}
