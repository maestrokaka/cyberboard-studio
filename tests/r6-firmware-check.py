#!/usr/bin/env python3
"""Offline firmware catalog and handoff checks; no USB/network/firmware writes."""
import importlib.util
import io
import json
import types
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("r6_firmware", ROOT / "backend" / "r6_firmware.py")
firmware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(firmware)


def catalog():
    return {"key": "CBR6", "version": "AM01R6.N40.r1.01.01", "update_time": "2026-09-22T17:29:26+08:00",
            "files": [{"name": "AM01R6.N40.r1.01.01.zip",
                       "url": "https://angrymiao-diy.oss-cn-shenzhen.aliyuncs.com/firmware/AM01R6.N40.r1.01.01_test.zip"}]}


class Reply(io.BytesIO):
    def __init__(self, body, url=firmware.CATALOG_URL, status=200):
        super().__init__(body)
        self.url, self.status, self.requested_size = url, status, None

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.requested_size = size
        return super().read(size)


class FirmwareChecks(unittest.TestCase):
    def identity(self, version="AM01R6.N40.r1.00.09", product="AM01R6"):
        return types.SimpleNamespace(product_id=product, version=version, port="synthetic-port-not-sent-to-catalog")

    def check(self, **kwargs):
        return firmware.check_firmware(self.identity(**kwargs), fetcher=catalog)

    def test_offline_without_device_does_not_contact_catalog(self):
        fetch = Mock(side_effect=AssertionError("unexpected online request"))
        result = firmware.check_firmware(None, fetcher=fetch)
        self.assertFalse(result["connected"] or result["catalogChecked"])
        self.assertEqual(result["comparison"], "unknown")
        fetch.assert_not_called()

    def test_other_keyboard_never_uses_r6_package(self):
        fetch = Mock(side_effect=AssertionError("unexpected online request"))
        result = firmware.check_firmware(self.identity(product="CB04"), fetcher=fetch)
        self.assertEqual(result["comparison"], "unsupported")
        self.assertFalse(result["supported"])
        fetch.assert_not_called()

    def test_supported_old_version_has_official_browser_handoff(self):
        result = self.check()
        self.assertEqual(result["comparison"], "update-available")
        self.assertEqual(result["updateMode"], "official-browser")
        self.assertEqual(result["officialUrl"], "https://diy.angrymiao.com/firmware/cyberboard-r6/")
        self.assertEqual(result["versionSource"], "live-usb")
        self.assertTrue(result["supported"] and result["catalogChecked"])
        self.assertFalse(result["inAppFlashSupported"] or result["packageDownloaded"] or result["packageSignatureVerified"])
        self.assertEqual(len(result["handoffSteps"]), 4)

    def test_matching_version_is_not_claimed_as_flash_success(self):
        result = self.check(version="AM01R6.N40.r1.01.01")
        self.assertEqual(result["comparison"], "up-to-date")
        self.assertNotIn("upgradeSuccess", result)
        self.assertFalse(result["packageDownloaded"])

    def test_newer_current_version_does_not_suggest_downgrade(self):
        result = self.check(version="AM01R6.N40.r1.10.00")
        self.assertEqual(result["comparison"], "newer")

    def test_hardware_variants_are_not_compared_only_by_numeric_suffix(self):
        self.assertEqual(self.check(version="AM01R6.N60.r1.00.01")["comparison"], "incomparable")

    def test_unknown_format_does_not_claim_latest(self):
        for version in ("", "unknown", "test-r6", "1.01.01", "AM01R6.N40.rdevelopment"):
            with self.subTest(version=version):
                self.assertEqual(self.check(version=version)["comparison"], "incomparable")

    def test_numeric_revision_comparison_and_trailing_zeros(self):
        self.assertEqual(firmware.compare_versions("AM01R6.N40.r1.9", "AM01R6.N40.r1.10"), "update-available")
        self.assertEqual(firmware.compare_versions("AM01R6.N40.r1.01", "AM01R6.N40.r1.1.0"), "up-to-date")
        self.assertEqual(firmware.compare_versions("AM01R6.N40.r10.0", "AM01R6.N40.r2.0"), "newer")

    def test_network_failure_preserves_live_version_but_latest_is_unknown(self):
        def fail():
            raise firmware.R6FirmwareError("firmware_catalog_unavailable", "offline")
        result = firmware.check_firmware(self.identity(), fetcher=fail)
        self.assertEqual(result["currentVersion"], "AM01R6.N40.r1.00.09")
        self.assertEqual(result["comparison"], "unknown")
        self.assertIsNone(result["latestVersion"])
        self.assertFalse(result["catalogChecked"])

    def test_wrong_catalog_model_is_rejected(self):
        value = catalog()
        value["key"] = "CBR4"
        with self.assertRaises(firmware.R6FirmwareError):
            firmware.parse_catalog(value)

    def test_package_filename_must_match_reported_version(self):
        value = catalog()
        value["files"][0]["name"] = "AM01R6.N40.r0.00.01.zip"
        with self.assertRaises(firmware.R6FirmwareError):
            firmware.parse_catalog(value)

    def test_only_exact_official_https_package_host_is_allowed(self):
        base = catalog()["files"][0]["url"]
        invalid = [base.replace("https:", "http:"), base.replace(".com/", ".com.evil.invalid/"),
                   base.replace("https://", "https://name:password@"), base.replace(".com/", ".com:8080/"),
                   base+"?redirect=https://evil.invalid", base+"#fragment", base.replace("/firmware/", "/other/"),
                   base.replace("/firmware/", "/firmware/../"), base.replace("/firmware/", "/firmware/%2e%2e/"),
                   base.replace("/firmware/", "/firmware/%0a/"), base.replace(".zip", ".exe"), "file:///tmp/firmware.zip"]
        for url in invalid:
            with self.subTest(url=url):
                self.assertFalse(firmware.allowed_package_url(url))
                value = catalog()
                value["files"][0]["url"] = url
                with self.assertRaises(firmware.R6FirmwareError):
                    firmware.parse_catalog(value)

    def test_malformed_catalog_shapes_are_rejected(self):
        for value in (None, [], {"key": "CBR6"}, {**catalog(), "files": []},
                      {**catalog(), "version": "CB04.1.01"}, {**catalog(), "changelog": []}):
            with self.subTest(value=value):
                with self.assertRaises(firmware.R6FirmwareError):
                    firmware.parse_catalog(value)

    def test_metadata_does_not_upgrade_hash_or_secure_name_into_signature_proof(self):
        value = catalog()
        value.update(sha256="f"*64, signed=True, signature="not independently verified")
        result = firmware.parse_catalog(value)
        self.assertEqual(result["sourceVerification"], "official-https-catalog")
        self.assertFalse(result["packageSignatureVerified"] or result["packageDownloaded"])
        self.assertNotIn("sha256", result)

    def test_catalog_transport_is_bounded_and_sends_no_device_data(self):
        reply = Reply(json.dumps(catalog()).encode())
        opener = types.SimpleNamespace(open=Mock(return_value=reply))
        value = firmware.fetch_catalog(opener=opener)
        self.assertEqual(value, catalog())
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, firmware.CATALOG_URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), firmware.CATALOG_QUERY)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 10)
        self.assertEqual(reply.requested_size, firmware.MAX_CATALOG_BYTES+1)

    def test_oversized_or_invalid_json_is_rejected(self):
        for raw in (b"x"*(firmware.MAX_CATALOG_BYTES+1), b"<html>error</html>", b"\xff"):
            with self.subTest(size=len(raw)):
                opener = types.SimpleNamespace(open=Mock(return_value=Reply(raw)))
                with self.assertRaises(firmware.R6FirmwareError):
                    firmware.fetch_catalog(opener=opener)

    def test_unexpected_response_origin_or_status_is_rejected(self):
        for response in (Reply(b"{}", url="https://evil.invalid/"), Reply(b"{}", status=503)):
            opener = types.SimpleNamespace(open=Mock(return_value=response))
            with self.assertRaises(firmware.R6FirmwareError):
                firmware.fetch_catalog(opener=opener)

    def test_redirect_handler_never_follows_an_unreviewed_target(self):
        handler = firmware.NoRedirects()
        self.assertIsNone(handler.redirect_request(None, None, 302, "redirect", {}, "https://evil.invalid/"))

    def test_network_exception_details_are_not_exposed(self):
        opener = types.SimpleNamespace(open=Mock(side_effect=urllib.error.URLError("private proxy detail")))
        with self.assertRaises(firmware.R6FirmwareError) as caught:
            firmware.fetch_catalog(opener=opener)
        self.assertNotIn("private proxy detail", str(caught.exception))
        self.assertEqual(caught.exception.code, "firmware_catalog_unavailable")

    def test_dispatch_uses_live_identity_and_never_payload_firmware(self):
        device = self.identity()
        bridge = types.SimpleNamespace(discover=Mock(return_value=device))
        with patch.object(firmware, "fetch_catalog", side_effect=catalog):
            result = firmware.dispatch(bridge, "r6FirmwareStatus", {"firmware": "AM01R6.N40.r99.99", "url": "https://evil.invalid"})
        self.assertEqual(result["currentVersion"], device.version)
        self.assertEqual(result["comparison"], "update-available")

    def test_dispatch_cannot_be_used_to_enter_bootloader_or_flash(self):
        bridge = types.SimpleNamespace(discover=Mock())
        for action in ("firmwareFlash", "enterUpgradeMode", "downloadPackage"):
            with self.assertRaises(firmware.R6FirmwareError):
                firmware.dispatch(bridge, action, {})
        bridge.discover.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
