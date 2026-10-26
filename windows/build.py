#!/usr/bin/env python3
"""Cross-publish the native Windows host and assemble a portable release package.

Requires .NET 10 SDK, Pillow, and the prepared runtime/python directory.
No installed device records are copied, and no device operation is executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import zipfile

WINDOWS = Path(__file__).resolve().parent
APP = WINDOWS.parent
CACHE = APP / ".tools/windows-build"
OUTPUT = APP / "build/windows/Cyberboard Studio"
ARCHIVE = APP / "build/Cyberboard-Studio-1.0.0-beta.15-Windows-x64.zip"
LOGO = APP / "web/assets/branding/product-icon/cyberboard-studio-approved-am-paw-v10.png"
SYSTEM_CREDENTIAL_MARKERS = ("DPAPI", "ProtectedData", "CryptProtectData", "CryptUnprotectData",
                             "CredRead", "CredWrite", "VaultEnumerate", "crypt32.dll")


def assert_local_key_storage():
    source = (WINDOWS / "src/AISettings.cs").read_text(encoding="utf-8")
    assembly = (OUTPUT / "Cyberboard Studio.dll").read_bytes()
    for marker in SYSTEM_CREDENTIAL_MARKERS:
        if marker in source or marker.encode("ascii") in assembly or marker.encode("utf-16-le") in assembly:
            raise RuntimeError("System credential path reintroduced in application host: " + marker)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cet_compatible(path):
    """Read the apphost's actual CET bit from the extended DLL debug record."""
    data = path.read_bytes()
    if data[:2] != b"MZ":
        raise RuntimeError("Apphost is not a Windows PE executable.")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise RuntimeError("Apphost PE header is invalid.")
    optional = pe + 24
    if struct.unpack_from("<H", data, optional)[0] != 0x20B:
        raise RuntimeError("Apphost must be PE32+ x64.")
    count = struct.unpack_from("<H", data, pe + 6)[0]
    sections = optional + struct.unpack_from("<H", data, pe + 20)[0]
    rva, size = struct.unpack_from("<II", data, optional + 112 + 6 * 8)
    if not rva or not size:
        return False
    for index in range(count):
        virtual_size, address, raw_size, raw_offset = struct.unpack_from("<IIII", data, sections + 40 * index + 8)
        if address <= rva < address + max(virtual_size, raw_size):
            offset = raw_offset + rva - address
            if size % 28 or offset + size > len(data):
                raise RuntimeError("Apphost debug directory is invalid.")
            for entry in range(offset, offset + size, 28):
                kind, length, _, pointer = struct.unpack_from("<IIII", data, entry + 12)
                if kind == 20:  # IMAGE_DEBUG_TYPE_EX_DLLCHARACTERISTICS
                    if length < 4 or pointer + length > len(data):
                        raise RuntimeError("Apphost CET record is invalid.")
                    return bool(struct.unpack_from("<I", data, pointer)[0] & 1)
            return False
    raise RuntimeError("Apphost debug directory cannot be mapped.")


def export_icon():
    from PIL import Image
    with Image.open(LOGO) as image:
        image.save(WINDOWS / "src/AppIcon.ico", format="ICO",
                   sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])


def assemble(nuget, dotnet, bootstrapper, windows10_compat=False):
    runtime = WINDOWS / "runtime/python"
    if not (runtime / "python.exe").is_file():
        raise RuntimeError("Prepare the embedded Windows Python runtime first.")
    if not (OUTPUT / "Cyberboard Studio.exe").is_file():
        raise RuntimeError("Publish the Windows executable before assembling.")
    assert_local_key_storage()
    actual_cet = cet_compatible(OUTPUT / "Cyberboard Studio.exe")
    if actual_cet != (not windows10_compat):
        raise RuntimeError("Apphost CET bit does not match the requested package. Re-publish before assembling.")
    resources = OUTPUT / "resources"
    if resources.exists():
        shutil.rmtree(resources)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    shutil.copytree(APP / "web", resources / "web", dirs_exist_ok=True, ignore=ignore)
    shutil.copytree(runtime, resources / "python", dirs_exist_ok=True, ignore=ignore)
    backend = resources / "backend"
    backend.mkdir(parents=True, exist_ok=True)
    for module in ("bridge.py", "kimi_ai.py", "lighting_recipe.py", "ai_images.py", "ai_quality.py", "speech_input.py", "keymap_codec.py", "companion.py", "miao_call.py", "agent_tasks.py", "codex_tasks.py", "codex_runtime.py", "codex_connection.py", "r6_audio.py", "r6_keymap.py", "r6_firmware.py"):
        shutil.copy2(APP / "backend" / module, backend / module)
    shutil.copy2(WINDOWS / "migrate-config.py", backend / "migrate-config.py")

    # Creative works/calibrated photos travel; a personal device baseline does not.
    data_file = resources / "web/data.js"
    source = data_file.read_text(encoding="utf-8")
    prefix = "window.STUDIO_DATA="
    if not source.startswith(prefix) or not source.rstrip().endswith(";"):
        raise RuntimeError("Unexpected bundled preview-data format.")
    data = json.loads(source[len(prefix):].rstrip().removesuffix(";"))
    data["baseConfig"] = None
    data["snapshot"] = {"productId": None, "firmware": None, "connected": False}
    # Factory base-layer labels suffice for offline layout and live-code lookup.
    # Custom Fn-layer assignments/read metadata are never included in the release.
    for key in data["keyLayout"]:
        key["bindings"] = key.get("bindings", [])[:1]
    data_file.write_text(prefix + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                         encoding="utf-8")
    (resources / "web/assets/keymap-layout.json").write_text(
        json.dumps({"kind": "cyberboard-physical-layout", "keys": data["keyLayout"]},
                   ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    dependency = OUTPUT / "Dependencies"
    dependency.mkdir(parents=True, exist_ok=True)
    installer = bootstrapper
    if not installer.is_file():
        raise RuntimeError("Missing official WebView2 bootstrapper.")
    shutil.copy2(installer, dependency / "MicrosoftEdgeWebview2Setup.exe")
    shutil.copy2(WINDOWS / "release-readme.txt", OUTPUT / "使用说明.txt")
    if windows10_compat:
        with (OUTPUT / "使用说明.txt").open("a", encoding="utf-8") as handle:
            handle.write("\nWindows 10 CET 兼容测试包\n"
                         "此包仅关闭 Cyberboard Studio 程序自身的 CET 兼容标记，"
                         "用于排查旧补丁 Windows 10 的运行时启动错误。\n"
                         "CET 是硬件栈保护；此包不启用该保护，不修改 Windows 系统安全设置。\n"
                         "普通版本保留 CET。建议更新系统补丁后使用普通版本。\n"
                         "用户已反馈此前 CET 兼容修复包可启动并完成同步；"
                         "本次完整包已交叉编译与离线检查，仍需实机确认。\n")
    shutil.copy2(WINDOWS / "migrate-config.cmd", OUTPUT / "迁移原配置.cmd")
    shutil.copy2(WINDOWS / "smoke-check.cmd", OUTPUT / "检查运行环境.cmd")
    shutil.copy2(WINDOWS / "diagnose-startup.cmd", OUTPUT / "诊断启动.cmd")

    # Preserve the licenses shipped by Microsoft along with the managed/native host.
    licenses = OUTPUT / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    package = nuget / "microsoft.web.webview2/1.0.4258.31"
    sdk_license = package / "LICENSE.txt"
    if not sdk_license.is_file():
        raise RuntimeError("Missing WebView2 SDK license from restored NuGet package.")
    shutil.copy2(sdk_license, licenses / "WebView2-SDK-LICENSE.txt")
    shutil.copy2(package / "NOTICE.txt", licenses / "WebView2-SDK-NOTICE.txt")
    runtime_config = json.loads((OUTPUT / "Cyberboard Studio.runtimeconfig.json").read_text(encoding="utf-8"))
    frameworks = {item["name"]: item["version"] for item in runtime_config["runtimeOptions"].get("includedFrameworks", [])}
    for component in ("microsoft.netcore.app.runtime.win-x64", "microsoft.windowsdesktop.app.runtime.win-x64"):
        framework = "Microsoft.WindowsDesktop.App" if "windowsdesktop" in component else "Microsoft.NETCore.App"
        version = frameworks.get(framework, "10.0.12")
        folder = nuget / component / version
        for name in ("LICENSE", "LICENSE.TXT", "THIRD-PARTY-NOTICES.TXT"):
            source = folder / name
            if source.is_file():
                shutil.copy2(source, licenses / (component + "-" + name))
    for name in ("LICENSE.txt", "ThirdPartyNotices.txt"):
        source = dotnet.parent / name
        if source.is_file():
            shutil.copy2(source, licenses / ("dotnet-" + name))
    # Debug symbols are development outputs; the complete managed runtime stays.
    (OUTPUT / "Cyberboard Studio.pdb").unlink(missing_ok=True)
    manifest = {
        "product": "Cyberboard Studio", "version": "1.0.0-beta.15", "rid": "win-x64",
        "native": "WinForms + WebView2", "dotnet": frameworks.get("Microsoft.NETCore.App", "10.0.12") + " self-contained",
        "webview2Sdk": "1.0.4258.31", "python": "3.12.10 embedded x64",
        "cli": "0.1.2 with AM01R6 and Windows patches",
        "includesDeviceBaseline": False, "startupAccessesUSB": False,
        "diagnosticStartup": True,
        "cetCompat": actual_cet, "windows10CompatibilityBuild": windows10_compat,
        "validation": "Cross-compiled on macOS; offline tests. Windows launch/USB not yet verified.",
        "logoSha256": sha256(LOGO), "executableSha256": sha256(OUTPUT / "Cyberboard Studio.exe"),
        "managedHostSha256": sha256(OUTPUT / "Cyberboard Studio.dll"),
        "hostSourceSha256": {path.relative_to(APP).as_posix(): sha256(path)
                             for path in sorted((WINDOWS / "src").iterdir())
                             if path.is_file() and path.suffix in (".cs", ".csproj", ".manifest")},
        "credentialStore": "provider-local-plain-files", "systemCredentialAccess": False,
        "webview2BootstrapperSha256": sha256(installer),
        "sources": {
            "dotnet": "https://builds.dotnet.microsoft.com/dotnet/release-metadata/10.0/releases.json",
            "webview2": "https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.4258.31",
            "bootstrapper": "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
            "cetCompatibility": "https://learn.microsoft.com/en-us/dotnet/core/compatibility/interop/9.0/cet-support",
        },
    }
    (OUTPUT / "release-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    files = sorted(path for path in OUTPUT.rglob("*") if path.is_file() and path.name != "SHA256SUMS.txt")
    checksums = "".join(f"{sha256(path)}  {path.relative_to(OUTPUT).as_posix()}\n" for path in files)
    (OUTPUT / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8")
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(OUTPUT.rglob("*")):
            if path.is_file():
                archive.write(path, (Path(OUTPUT.name) / path.relative_to(OUTPUT)).as_posix())
    (ARCHIVE.with_suffix(".zip.sha256")).write_text(f"{sha256(ARCHIVE)}  {ARCHIVE.name}\n", encoding="utf-8")
    print(f"Portable package: {ARCHIVE} ({ARCHIVE.stat().st_size / 1024 / 1024:.1f} MiB)")


def main():
    global OUTPUT, ARCHIVE
    parser = argparse.ArgumentParser(description=__doc__)
    cached_dotnet = CACHE / "dotnet" / ("dotnet.exe" if os.name == "nt" else "dotnet")
    parser.add_argument("--dotnet", default=str(cached_dotnet) if cached_dotnet.is_file() else shutil.which("dotnet") or str(cached_dotnet),
                        help=".NET SDK executable; an external or system SDK is also supported.")
    parser.add_argument("--nuget", type=Path, default=CACHE / "nuget",
                        help="NuGet package cache used for restore and bundled licenses.")
    parser.add_argument("--bootstrapper", type=Path,
                        help="Official MicrosoftEdgeWebview2Setup.exe; default searches the app's .tools download cache.")
    parser.add_argument("--assemble-only", action="store_true")
    parser.add_argument("--windows10-compat", action="store_true",
                        help="Build a separate CET opt-out test package for unpatched Windows 10; leaves the normal package untouched.")
    args = parser.parse_args()
    if args.windows10_compat:
        OUTPUT = APP / "build/windows10-compat/Cyberboard Studio"
        ARCHIVE = APP / "build/Cyberboard-Studio-1.0.0-beta.15-Windows10-Compatibility-x64.zip"
    args.nuget = args.nuget.expanduser().resolve()
    dotnet = Path(shutil.which(args.dotnet) or args.dotnet).expanduser().resolve()
    if not args.assemble_only and not dotnet.is_file():
        parser.error(".NET SDK not found. Install .NET 10 SDK or pass --dotnet /path/to/dotnet.")
    if args.bootstrapper is None:
        candidates = [CACHE / "downloads/MicrosoftEdgeWebview2Setup.exe",
                      CACHE / "downloads/webview2-bootstrapper.exe",
                      CACHE / "MicrosoftEdgeWebview2Setup.exe",
                      WINDOWS / "installer/MicrosoftEdgeWebview2Setup.exe"]
        args.bootstrapper = next((path for path in candidates if path.is_file()), candidates[0])
    args.bootstrapper = args.bootstrapper.expanduser().resolve()
    if not args.bootstrapper.is_file():
        parser.error("WebView2 bootstrapper not found. Pass --bootstrapper /path/to/MicrosoftEdgeWebview2Setup.exe.")
    export_icon()
    if not args.assemble_only:
        if OUTPUT.exists():
            shutil.rmtree(OUTPUT)
        env = os.environ.copy()
        env.update(DOTNET_CLI_HOME=str(CACHE / "dotnet-home"),
                   NUGET_PACKAGES=str(args.nuget),
                   DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
                   DOTNET_GENERATE_ASPNET_CERTIFICATE="false")
        command = [str(dotnet), "publish", str(WINDOWS / "src/CyberboardStudio.Windows.csproj"),
                   "-c", "Release", "-r", "win-x64", "--self-contained", "true",
                   "-p:CETCompat=" + ("false" if args.windows10_compat else "true"),
                   "--output", str(OUTPUT), "--nologo"]
        if args.windows10_compat:
            # Keep compiler outputs/apphost intermediates separate from the
            # standard build. The NuGet assets still describe the same runtime.
            command.extend(["-p:IntermediateOutputPath=" + str(APP / "build/windows10-compat/obj") + "/",
                            "-p:OutputPath=" + str(APP / "build/windows10-compat/bin") + "/"])
        subprocess.run(command, check=True, env=env, cwd=APP)
    assemble(args.nuget, dotnet, args.bootstrapper, args.windows10_compat)


if __name__ == "__main__":
    main()
