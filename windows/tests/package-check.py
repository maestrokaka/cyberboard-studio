"""Validate the actual Windows release offline, without running an executable."""
from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path
import struct
import sys
import unittest
import zipfile

APP = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--package", type=Path, default=APP / "build/windows/Cyberboard Studio")
parser.add_argument("--archive", type=Path, default=APP / "build/Cyberboard-Studio-1.0.0-rc.2-Windows-x64.zip")
parser.add_argument("--expected-cet", choices=["enabled", "disabled"], default="enabled")
options, unittest_args = parser.parse_known_args()
PACKAGE = options.package
ARCHIVE = options.archive


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
                    "resources/backend/ai_quality.py", "resources/backend/speech_input.py", "resources/backend/keymap_codec.py",
                    "resources/web/index.html", "resources/web/data.js", "resources/web/ai-client.js", "resources/web/chat-client.js", "resources/web/creation.css", "resources/web/library-client.js", "迁移原配置.cmd",
                    "检查运行环境.cmd", "诊断启动.cmd", "使用说明.txt", "Dependencies/MicrosoftEdgeWebview2Setup.exe"]
        for name in required:
            self.assertTrue((PACKAGE / name).is_file(), name)
        self.assertFalse((PACKAGE / "Microsoft.Web.WebView2.Wpf.dll").exists())
        for removed in ("assets/desk.jpg", "assets/photos/r4-cloud-perspective.jpg", "assets/photos/r6-launch-front.png"):
            self.assertFalse((PACKAGE / "resources/web" / removed).exists(), removed)
        config = json.loads((PACKAGE / "Cyberboard Studio.runtimeconfig.json").read_text())
        self.assertEqual(config["runtimeOptions"]["tfm"], "net10.0")
        release = json.loads((PACKAGE / "release-manifest.json").read_text())
        self.assertTrue(release["diagnosticStartup"])
        self.assertEqual(release["version"], "1.0.0-rc.2")
        self.assertEqual(release["executableSha256"], digest(PACKAGE / "Cyberboard Studio.exe"))
        self.assertEqual(release["managedHostSha256"], digest(PACKAGE / "Cyberboard Studio.dll"))
        self.assertEqual(release["hostSourceSha256"],
                         {path.relative_to(APP).as_posix(): digest(path)
                          for path in sorted((APP / "windows/src").iterdir())
                          if path.is_file() and path.suffix in (".cs", ".csproj", ".manifest")})
        self.assertEqual(release["credentialStore"], "provider-local-plain-files")
        self.assertIs(release["systemCredentialAccess"], False)
        host_source = (APP / "windows/src/StudioForm.cs").read_text(encoding="utf-8")
        self.assertIn('ReleaseVersion = "1.0.0-rc.2"', host_source)
        self.assertIn('version = ReleaseVersion', host_source)
        self.assertIn('1.0.0-rc.2'.encode("utf-16-le"),
                      (PACKAGE / "Cyberboard Studio.dll").read_bytes())
        self.assertEqual(release["webview2BootstrapperSha256"], digest(PACKAGE / "Dependencies/MicrosoftEdgeWebview2Setup.exe"))
        self.assertIs(release["includesDeviceBaseline"], False)
        self.assertIs(release["startupAccessesUSB"], False)
        self.assertTrue((PACKAGE / "使用说明.txt").read_text(encoding="utf-8").startswith("Cyberboard Studio 1.0.0-rc.2"))
        self.assertIn("includedFrameworks", config["runtimeOptions"], "Runtime must be self-contained")
        for name in ("index.html", "data.js", "app.js", "studio-model.js", "ai-client.js", "chat-client.js", "creation.css", "library-client.js", "keymap-client.js", "keymap.css", "voice-input.js", "voice-input.css", "preview-selector.js", "preview-engine.js", "polish.css", "dialogs.js", "assets/builtin-default-pages.json", "assets/support/wechat-pay.jpg", "assets/photos/r4-fluo-front.jpg", "assets/photos/r4-bebop-front.jpg"):
            self.assertEqual(digest(PACKAGE / "resources/web" / name), digest(APP / "web" / name), name)
        self.assertTrue(any((PACKAGE / "resources/python").rglob("_imagingcms*.pyd")), "Color conversion native module is missing")
        for name in ("bridge.py", "kimi_ai.py", "lighting_recipe.py", "ai_images.py", "ai_quality.py", "speech_input.py", "keymap_codec.py"):
            self.assertEqual(digest(PACKAGE / "resources/backend" / name), digest(APP / "backend" / name), name)

    def test_executable_and_native_dependencies_are_windows_x64(self):
        for name in ("Cyberboard Studio.exe", "coreclr.dll", "hostfxr.dll", "WebView2Loader.dll",
                     "resources/python/python.exe", "resources/python/python312.dll"):
            data, offset = pe_header(PACKAGE / name)
            self.assertEqual(struct.unpack_from("<H", data, offset + 4)[0], 0x8664, name)
        data, offset = pe_header(PACKAGE / "Cyberboard Studio.exe")
        self.assertEqual(struct.unpack_from("<H", data, offset + 24 + 68)[0], 2, "Native app has GUI subsystem")
        certificate_offset, certificate_size = struct.unpack_from("<II", data, offset + 24 + 112 + 4 * 8)
        self.assertEqual((certificate_offset, certificate_size), (0, 0), "This release must remain accurately described as unsigned, with no inherited Authenticode certificate")

    def test_app_credentials_have_no_system_vault_or_encryption_routes(self):
        # Scan only our own managed host. WebView2 and the .NET runtime can use
        # Windows system APIs for unrelated browser/runtime behavior.
        source = "\n".join(path.read_text(encoding="utf-8") for path in (APP / "windows/src").glob("*.cs"))
        assembly = (PACKAGE / "Cyberboard Studio.dll").read_bytes()
        forbidden = ("DPAPI", "ProtectedData", "CryptProtectData", "CryptUnprotectData",
                     "CredRead", "CredWrite", "VaultEnumerate", "crypt32.dll")
        for marker in forbidden:
            self.assertNotIn(marker, source, marker)
            self.assertNotIn(marker.encode("ascii"), assembly, marker)
            self.assertNotIn(marker.encode("utf-16-le"), assembly, marker)
        for removed in ("ICredentialVault? legacy", "legacy?.Read", 'Path.Combine(state, "credentials")'):
            self.assertNotIn(removed, source)
        self.assertIn('new LocalFileCredentialVault(Path.Combine(state, "ai-keys"))', source)

    def test_complete_web_python_and_migration_sources_match_the_release(self):
        def files(directory):
            return {path.relative_to(directory).as_posix(): path for path in directory.rglob("*")
                    if path.is_file() and not any(part == "__pycache__" or part == ".DS_Store" or part.endswith(".pyc")
                                                  for part in path.relative_to(directory).parts)}

        for source, shipped, rewritten in ((APP / "web", PACKAGE / "resources/web", {"data.js", "assets/keymap-layout.json"}),
                                            (APP / "windows/runtime/python", PACKAGE / "resources/python", set())):
            expected, actual = files(source), files(shipped)
            self.assertEqual(set(actual), set(expected), "Complete resource inventory must match " + str(source))
            for relative in sorted(set(expected) - rewritten):
                self.assertEqual(digest(actual[relative]), digest(expected[relative]), relative)
        self.assertEqual(digest(PACKAGE / "resources/backend/migrate-config.py"), digest(APP / "windows/migrate-config.py"))

    def test_apphost_cet_bit_matches_the_selected_package(self):
        sys.path.insert(0, str(APP / "windows"))
        from build import cet_compatible
        expected = options.expected_cet == "enabled"
        self.assertEqual(cet_compatible(PACKAGE / "Cyberboard Studio.exe"), expected)
        manifest = json.loads((PACKAGE / "release-manifest.json").read_text())
        if not expected:
            self.assertIs(manifest["cetCompat"], False)
            self.assertIs(manifest["windows10CompatibilityBuild"], True)
            self.assertIn("CET 是硬件栈保护", (PACKAGE / "使用说明.txt").read_text())

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
        canonical_source = (APP / "web/data.js").read_text(encoding="utf-8")
        original = json.loads(canonical_source[len("window.STUDIO_DATA="):].strip().removesuffix(";"))
        self.assertGreaterEqual(len(original["designs"]), 3, "Release must retain the original built-in works")
        self.assertEqual(data["designs"], original["designs"], "Every released work must match the current prepared data, including new presets")
        self.assertEqual(data["legacyDesigns"], original["legacyDesigns"], "Legacy draft compatibility must keep the complete original RGB")
        self.assertEqual(data["presetPreviews"], original["presetPreviews"])
        self.assertFalse({work["id"] for work in data["designs"]} & {work["id"] for work in data["legacyDesigns"]}, "Legacy works must not silently re-enter the main catalog")
        self.assertEqual(len(data["keyLayout"]), 81)
        self.assertTrue(all(len(key["bindings"]) == 1 for key in data["keyLayout"]))
        layout = json.loads((PACKAGE / "resources/web/assets/keymap-layout.json").read_text())
        self.assertEqual(set(layout), {"kind", "keys"})
        self.assertEqual(layout["keys"], data["keyLayout"])
        for path in PACKAGE.rglob("*"):
            if path.is_file():
                self.assertNotIn(path.name, {"current.json", "meta.json", ".lock", "workspace.json", "ai-settings.json", "voice-settings.json"})
                self.assertNotIn("/credentials/", path.relative_to(PACKAGE).as_posix())
                self.assertNotIn("/ai-keys/", path.relative_to(PACKAGE).as_posix())
                self.assertNotIn("/voice-keys/", path.relative_to(PACKAGE).as_posix())
                self.assertNotIn("/history/", path.relative_to(PACKAGE).as_posix())
        self.assertNotIn("/Users/sheva", source)
        self.assertFalse((PACKAGE / "resources/python/pyvenv.cfg").exists())

    def test_photo_and_approved_logo_resources_are_preserved(self):
        web = PACKAGE / "resources/web"
        logo = "assets/branding/product-icon/cyberboard-studio-approved-am-paw-v10.png"
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

    def test_serial_detection_fix_is_in_the_actual_package(self):
        runtime = PACKAGE / "resources/python"
        relative = "cyberboard/_tools/cb_device.py"
        shipped = runtime / "Lib/site-packages" / relative
        self.assertEqual(digest(shipped), digest(APP / "vendor/cyberboard-cli" / relative))
        manifest = json.loads((runtime / "runtime-manifest.json").read_text())
        self.assertEqual(manifest["cli"]["source_files_sha256"][relative], digest(shipped))
        self.assertIn("def probe_with_diagnostics(", shipped.read_text())
        self.assertIn("serial_keymap_failed", (PACKAGE / "resources/backend/bridge.py").read_text())

    def test_first_setup_is_in_the_actual_package_without_fake_baseline(self):
        backend = (PACKAGE / "resources/backend/bridge.py").read_text()
        web = (PACKAGE / "resources/web/app.js").read_text()
        for name in ("def initializePlan(", "def execute_initialization(", "confirmInitialization", "live-keymap-only"):
            self.assertIn(name, backend)
        for name in ("initializationAcknowledged", "initializePlan", "confirmInitialization", "live-keymap-only"):
            self.assertIn(name, web)
        guide = (PACKAGE / "使用说明.txt").read_text(encoding="utf-8")
        self.assertIn("没有可信记录时可准备首次配置", guide)
        self.assertIn("不是旧完整配置备份", guide)
        self.assertIn("不盲目再次初始化", guide)
        self.assertFalse((PACKAGE / "resources/python/devices").exists())

    def test_official_builtin_modes_template_and_targeted_workflow_are_shipped(self):
        template = json.loads((PACKAGE / "resources/web/assets/builtin-default-pages.json").read_text())
        self.assertEqual(template, json.loads((APP / "data/builtin-default-pages.json").read_text()))
        self.assertEqual(template["kind"], "cyberboard-standard-builtin-pages")
        self.assertEqual([page["page_index"] for page in template["pages"]], list(range(5)))
        self.assertEqual([page["valid"] for page in template["pages"]], [1, 1, 1, 0, 0])
        self.assertNotIn("key_layer", template)
        self.assertTrue(template["source"]["url"].startswith("https://diy.angrymiao.com/"))
        backend = (PACKAGE / "resources/backend/bridge.py").read_text()
        for name in ("def readConfiguration(", "def builtInPlan(", "builtin-modes"):
            self.assertIn(name, backend)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *unittest_args], verbosity=2)
