"""Validate the actual Windows release offline, without running an executable."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest
import zipfile

APP = Path(__file__).resolve().parents[2]
PACKAGE = APP / "build/windows/Cyberboard Studio"
ARCHIVE = APP / "build/Cyberboard-Studio-0.2.2-Windows-x64.zip"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pe_header(path):
    data = path.read_bytes()
    assert data[:2] == b"MZ", path
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[offset:offset + 4] == b"PE\0\0", path
    return data, offset


class PackageChecks(unittest.TestCase):
    def test_required_runtime_and_host_files(self):
        required = ["Cyberboard Studio.exe", "Cyberboard Studio.dll", "AppIcon.ico",
                    "coreclr.dll", "hostfxr.dll", "System.Windows.Forms.dll",
                    "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
                    "WebView2Loader.dll", "resources/python/python.exe",
                    "resources/python/python312.dll", "resources/python/python312.zip",
                    "resources/backend/bridge.py", "resources/backend/migrate-config.py",
                    "resources/backend/kimi_ai.py", "resources/backend/lighting_recipe.py", "resources/backend/ai_images.py",
                    "resources/web/index.html", "resources/web/data.js", "resources/web/ai-client.js", "resources/web/library-client.js", "迁移原配置.cmd",
                    "检查运行环境.cmd", "使用说明.txt", "Dependencies/MicrosoftEdgeWebview2Setup.exe"]
        for name in required:
            self.assertTrue((PACKAGE / name).is_file(), name)
        self.assertFalse((PACKAGE / "Microsoft.Web.WebView2.Wpf.dll").exists())
        config = json.loads((PACKAGE / "Cyberboard Studio.runtimeconfig.json").read_text())
        self.assertEqual(config["runtimeOptions"]["tfm"], "net10.0")
        self.assertIn("includedFrameworks", config["runtimeOptions"], "Runtime must be self-contained")
        for name in ("index.html", "app.js", "studio-model.js", "ai-client.js", "library-client.js", "polish.css", "dialogs.js", "assets/support/wechat-pay.jpg"):
            self.assertEqual(digest(PACKAGE / "resources/web" / name), digest(APP / "web" / name), name)
        self.assertTrue(any((PACKAGE / "resources/python").rglob("_imagingcms*.pyd")), "Color conversion native module is missing")
        for name in ("bridge.py", "kimi_ai.py", "lighting_recipe.py", "ai_images.py"):
            self.assertEqual(digest(PACKAGE / "resources/backend" / name), digest(APP / "backend" / name), name)

    def test_executable_and_native_dependencies_are_windows_x64(self):
        for name in ("Cyberboard Studio.exe", "coreclr.dll", "hostfxr.dll", "WebView2Loader.dll",
                     "resources/python/python.exe", "resources/python/python312.dll"):
            data, offset = pe_header(PACKAGE / name)
            self.assertEqual(struct.unpack_from("<H", data, offset + 4)[0], 0x8664, name)
        data, offset = pe_header(PACKAGE / "Cyberboard Studio.exe")
        self.assertEqual(struct.unpack_from("<H", data, offset + 24 + 68)[0], 2, "Native app has GUI subsystem")

    def test_every_shipped_file_hash_and_archive_integrity(self):
        entries = {}
        for line in (PACKAGE / "SHA256SUMS.txt").read_text().splitlines():
            expected, name = line.split("  ", 1)
            entries[name] = expected
            self.assertEqual(digest(PACKAGE / name), expected, name)
        actual = {path.relative_to(PACKAGE).as_posix() for path in PACKAGE.rglob("*")
                  if path.is_file() and path.name != "SHA256SUMS.txt"}
        self.assertEqual(set(entries), actual)
        with zipfile.ZipFile(ARCHIVE) as archive:
            self.assertIsNone(archive.testzip())
            prefix = PACKAGE.name + "/"
            self.assertEqual(set(archive.namelist()), {prefix + name for name in actual | {"SHA256SUMS.txt"}})
        self.assertEqual(digest(ARCHIVE), ARCHIVE.with_suffix(".zip.sha256").read_text().split()[0])

    def test_no_personal_device_state_or_false_baseline(self):
        source = (PACKAGE / "resources/web/data.js").read_text(encoding="utf-8")
        data = json.loads(source[len("window.STUDIO_DATA="):].strip().removesuffix(";"))
        self.assertIsNone(data["baseConfig"])
        self.assertEqual(data["snapshot"], {"productId": None, "firmware": None, "connected": False})
        self.assertEqual(len(data["designs"]), 3)
        self.assertEqual(len(data["keyLayout"]), 81)
        self.assertTrue(all(len(key["bindings"]) == 1 for key in data["keyLayout"]))
        layout = json.loads((PACKAGE / "resources/web/assets/keymap-layout.json").read_text())
        self.assertEqual(set(layout), {"kind", "keys"})
        for path in PACKAGE.rglob("*"):
            if path.is_file():
                self.assertNotIn(path.name, {"current.json", "meta.json", ".lock", "workspace.json", "ai-settings.json"})
                self.assertNotIn("/credentials/", path.relative_to(PACKAGE).as_posix())
                self.assertNotIn("/history/", path.relative_to(PACKAGE).as_posix())
        self.assertNotIn("/Users/sheva", source)
        self.assertFalse((PACKAGE / "resources/python/pyvenv.cfg").exists())

    def test_photo_and_approved_logo_resources_are_preserved(self):
        web = PACKAGE / "resources/web"
        logo = "assets/branding/product-icon/cyberboard-studio-photo-contour-v6-paw-180.png"
        self.assertEqual(digest(web / logo), digest(APP / "web" / logo))
        for source in (APP / "web/assets").glob("*.jpg"):
            self.assertEqual(digest(web / "assets" / source.name), digest(source))
        header = (PACKAGE / "AppIcon.ico").read_bytes()[:6]
        self.assertEqual(struct.unpack("<HHH", header), (0, 1, 7))

    def test_runtime_import_paths_are_portable_and_commands_are_offline(self):
        paths = (PACKAGE / "resources/python/python312._pth").read_text()
        self.assertIn("Lib/site-packages", paths)
        self.assertIn("../backend", paths)
        self.assertNotIn("/Users/", paths)
        smoke = (PACKAGE / "检查运行环境.cmd").read_text()
        migration = (PACKAGE / "迁移原配置.cmd").read_text()
        self.assertIn("-X utf8", smoke)
        self.assertIn("-X utf8", migration)
        self.assertNotIn("--execute", smoke + migration)
        self.assertNotIn(" detect", smoke + migration)

    def test_license_and_provenance_files_are_present(self):
        for name in ("licenses/WebView2-SDK-LICENSE.txt", "licenses/WebView2-SDK-NOTICE.txt",
                     "licenses/microsoft.netcore.app.runtime.win-x64-LICENSE.TXT",
                     "licenses/microsoft.windowsdesktop.app.runtime.win-x64-LICENSE",
                     "resources/python/LICENSE.txt", "resources/python/THIRD-PARTY-NOTICES.txt",
                     "resources/python/licenses/pyserial-BSD-3-Clause.txt",
                     "resources/python/runtime-manifest.json", "release-manifest.json"):
            self.assertTrue((PACKAGE / name).is_file(), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
