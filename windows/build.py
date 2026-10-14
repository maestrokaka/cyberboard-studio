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
import subprocess
import zipfile

WINDOWS = Path(__file__).resolve().parent
APP = WINDOWS.parent
CACHE = APP / ".tools/windows-build"
OUTPUT = APP / "build/windows/Cyberboard Studio"
ARCHIVE = APP / "build/Cyberboard-Studio-0.2.2-Windows-x64.zip"
LOGO = APP / "web/assets/branding/product-icon/cyberboard-studio-photo-contour-v6-paw-180.png"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def export_icon():
    from PIL import Image
    with Image.open(LOGO) as image:
        image.save(WINDOWS / "src/AppIcon.ico", format="ICO",
                   sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])


def assemble(nuget, dotnet, bootstrapper):
    runtime = WINDOWS / "runtime/python"
    if not (runtime / "python.exe").is_file():
        raise RuntimeError("Prepare the embedded Windows Python runtime first.")
    if not (OUTPUT / "Cyberboard Studio.exe").is_file():
        raise RuntimeError("Publish the Windows executable before assembling.")
    resources = OUTPUT / "resources"
    if resources.exists():
        shutil.rmtree(resources)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    shutil.copytree(APP / "web", resources / "web", dirs_exist_ok=True, ignore=ignore)
    shutil.copytree(runtime, resources / "python", dirs_exist_ok=True, ignore=ignore)
    backend = resources / "backend"
    backend.mkdir(parents=True, exist_ok=True)
    for module in ("bridge.py", "kimi_ai.py", "lighting_recipe.py", "ai_images.py"):
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
    shutil.copy2(WINDOWS / "migrate-config.cmd", OUTPUT / "迁移原配置.cmd")
    shutil.copy2(WINDOWS / "smoke-check.cmd", OUTPUT / "检查运行环境.cmd")

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
        "product": "Cyberboard Studio", "version": "0.2.2", "rid": "win-x64",
        "native": "WinForms + WebView2", "dotnet": frameworks.get("Microsoft.NETCore.App", "10.0.12") + " self-contained",
        "webview2Sdk": "1.0.4258.31", "python": "3.12.10 embedded x64",
        "cli": "0.1.2 with AM01R6 and Windows patches",
        "includesDeviceBaseline": False, "startupAccessesUSB": False,
        "validation": "Cross-compiled on macOS; offline tests. Windows launch/USB not yet verified.",
        "logoSha256": sha256(LOGO), "executableSha256": sha256(OUTPUT / "Cyberboard Studio.exe"),
        "webview2BootstrapperSha256": sha256(installer),
        "sources": {
            "dotnet": "https://builds.dotnet.microsoft.com/dotnet/release-metadata/10.0/releases.json",
            "webview2": "https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.4258.31",
            "bootstrapper": "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
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
    parser = argparse.ArgumentParser(description=__doc__)
    cached_dotnet = CACHE / "dotnet" / ("dotnet.exe" if os.name == "nt" else "dotnet")
    parser.add_argument("--dotnet", default=str(cached_dotnet) if cached_dotnet.is_file() else shutil.which("dotnet") or str(cached_dotnet),
                        help=".NET SDK executable; an external or system SDK is also supported.")
    parser.add_argument("--nuget", type=Path, default=CACHE / "nuget",
                        help="NuGet package cache used for restore and bundled licenses.")
    parser.add_argument("--bootstrapper", type=Path,
                        help="Official MicrosoftEdgeWebview2Setup.exe; default searches the app's .tools download cache.")
    parser.add_argument("--assemble-only", action="store_true")
    args = parser.parse_args()
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
        subprocess.run([str(dotnet), "publish", str(WINDOWS / "src/CyberboardStudio.Windows.csproj"),
                        "-c", "Release", "-r", "win-x64", "--self-contained", "true",
                        "--output", str(OUTPUT), "--nologo"], check=True, env=env, cwd=APP)
    assemble(args.nuget, dotnet, args.bootstrapper)


if __name__ == "__main__":
    main()
