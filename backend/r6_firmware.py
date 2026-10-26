"""Read-only R6 firmware identification/catalog comparison and official handoff.

The application does not enter bootloader mode, fetch a firmware binary, or
flash a keyboard. The official browser updater remains responsible for DFU.
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit


OFFICIAL_URL = "https://diy.angrymiao.com/firmware/cyberboard-r6/"
CATALOG_URL = "https://diy.angrymiao.com/api/firmware/check"
PACKAGE_HOST = "angrymiao-diy.oss-cn-shenzhen.aliyuncs.com"
MAX_CATALOG_BYTES = 64 * 1024
REQUEST_TIMEOUT_SECONDS = 10
# Public, fixed catalog parameters shipped in the manufacturer's web page.
# This is not an account credential and never includes the user's model keys.
CATALOG_QUERY = {"key": "CBR6", "password": "qaz028"}
HANDOFF_STEPS = (
    "先保留完整配置记录；本机灯效记录不是从键盘读取的完整备份。",
    "关闭占用键盘的配置窗口，在 Chrome 或 Edge 打开官网固件页面。",
    "在官网确认 R6 型号及目标版本，按官网步骤选择键盘和升级设备。",
    "官网完成后先断开官网连接，返回本 App 重新检查型号和固件版本。",
)


class R6FirmwareError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _text(value, maximum):
    return isinstance(value, str) and 0 < len(value) <= maximum and \
        not any(ord(char) < 32 or ord(char) == 127 for char in value)


def allowed_package_url(value):
    if not _text(value, 2048):
        return False
    try:
        url = urlsplit(value)
        path = unquote(url.path)
        return url.scheme == "https" and url.hostname == PACKAGE_HOST and url.port in (None, 443) and \
            not url.username and not url.password and not url.query and not url.fragment and \
            _text(path, 2048) and path.startswith("/firmware/") and path.lower().endswith(".zip") and \
            "\\" not in path and not any(part in (".", "..") for part in path.split("/"))
    except ValueError:
        return False


def parse_catalog(value):
    """Accept only the model and package host used by the official R6 page."""
    if not isinstance(value, dict) or value.get("key") != "CBR6":
        raise R6FirmwareError("firmware_catalog_invalid", "官网固件目录的型号不匹配，暂不能比较版本。")
    version, files = value.get("version"), value.get("files")
    if not _text(version, 96) or not version.startswith("AM01R6.") or \
            not isinstance(files, list) or not 1 <= len(files) <= 20:
        raise R6FirmwareError("firmware_catalog_invalid", "官网未返回可核对的 R6 固件版本。")
    package = next((item for item in files if isinstance(item, dict) and item.get("name") == version + ".zip"), None)
    if package is None or not allowed_package_url(package.get("url")):
        raise R6FirmwareError("firmware_catalog_invalid", "官网固件包来源未通过检查，请直接在官网核对。")
    changelog = value.get("changelog", "")
    if not isinstance(changelog, str) or len(changelog) > 8192:
        raise R6FirmwareError("firmware_catalog_invalid", "官网固件说明格式无法识别。")
    updated = value.get("update_time")
    return {"version": version, "fileName": package["name"], "packageUrl": package["url"],
            "changelog": changelog, "updatedAt": updated if _text(updated, 64) else None,
            "source": CATALOG_URL, "sourceVerification": "official-https-catalog",
            "packageSignatureVerified": False, "packageDownloaded": False}


def fetch_catalog(*, opener=None):
    """Fetch metadata only with bounded size, TLS verification and no redirects."""
    request = urllib.request.Request(CATALOG_URL, data=json.dumps(CATALOG_QUERY).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Accept": "application/json"},
                                     method="POST")
    if opener is None:
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()), NoRedirects())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if response.geturl() != CATALOG_URL or response.status != 200:
                raise R6FirmwareError("firmware_catalog_unavailable", "官网固件服务暂不可用，请稍后再检查。")
            raw = response.read(MAX_CATALOG_BYTES + 1)
            if len(raw) > MAX_CATALOG_BYTES:
                raise R6FirmwareError("firmware_catalog_invalid", "官网固件目录超出读取范围，请直接在官网核对。")
        return json.loads(raw.decode("utf-8"))
    except R6FirmwareError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError):
        raise R6FirmwareError("firmware_catalog_unavailable", "无法连接官网固件服务；当前版本已读取，最新版本暂无法确认。") from None
    except (UnicodeError, ValueError):
        raise R6FirmwareError("firmware_catalog_invalid", "官网固件目录格式无法识别，请直接在官网核对。") from None


def version_parts(value):
    """Compare revisions only inside the same R6 hardware/firmware family."""
    if not _text(value, 96):
        return None
    match = re.fullmatch(r"(AM01R6\.[A-Za-z0-9_-]+\.r)(\d+(?:\.\d+){1,7})", value, re.IGNORECASE)
    if match is None:
        return None
    return match[1].upper(), tuple(int(part) for part in match[2].split("."))


def compare_versions(current, latest):
    left, right = version_parts(current), version_parts(latest)
    if left is None or right is None or left[0] != right[0]:
        return "incomparable"
    size = max(len(left[1]), len(right[1]))
    left_values, right_values = left[1] + (0,) * (size-len(left[1])), right[1] + (0,) * (size-len(right[1]))
    return "update-available" if left_values < right_values else "newer" if left_values > right_values else "up-to-date"


def check_firmware(identity, *, fetcher=None):
    """identity must come from the bridge's live, read-only USB discovery."""
    result = {"connected": identity is not None, "supported": False, "productId": None,
              "currentVersion": None, "latestVersion": None, "comparison": "unknown",
              "updateMode": "official-browser", "inAppFlashSupported": False, "officialUrl": OFFICIAL_URL,
              "handoffSteps": list(HANDOFF_STEPS), "versionSource": "none", "catalogSource": CATALOG_URL,
              "catalogChecked": False, "packageSignatureVerified": False, "packageDownloaded": False,
              "message": "连接 R6 后可读取当前固件，并查询官网版本。"}
    if identity is None:
        return result
    product_id = str(getattr(identity, "product_id", "") or "").strip()
    current = str(getattr(identity, "version", "") or "").strip()
    result.update(productId=product_id, currentVersion=current if _text(current, 96) else None, versionSource="live-usb")
    if product_id.upper() != "AM01R6":
        result.update(comparison="unsupported", message="当前固件检查与官网升级入口仅适用于 CYBERBOARD R6。")
        return result
    result["supported"] = True
    try:
        catalog = parse_catalog((fetcher or fetch_catalog)())
    except R6FirmwareError as error:
        result.update(errorCode=error.code, message=error.message)
        return result
    except (OSError, ValueError, TypeError):
        result.update(errorCode="firmware_catalog_unavailable", message="官网版本暂无法确认，请稍后再检查。")
        return result
    comparison = compare_versions(current, catalog["version"])
    messages = {"update-available": "官网有更新版本，可前往官网按步骤升级。",
                "up-to-date": "当前固件版本与官网发布版本一致。",
                "newer": "当前版本高于官网目录版本，请勿仅为一致而降级。",
                "incomparable": "当前版本与官网版本的系列或格式不同，请先在官网核对兼容性。"}
    result.update(latestVersion=catalog["version"], comparison=comparison, catalog=catalog, catalogChecked=True,
                  checkedAt=datetime.now(timezone.utc).isoformat(timespec="seconds"), message=messages[comparison])
    return result


def dispatch(bridge, action, payload):
    if action != "r6FirmwareStatus" or not isinstance(payload, dict):
        raise R6FirmwareError("firmware_action_invalid", "固件操作无效，请重新检查版本。")
    # discover performs the existing, short-lived identity reads and releases
    # its port before the network request. No port survives the browser handoff.
    return check_firmware(bridge.discover(payload))
