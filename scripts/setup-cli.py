#!/usr/bin/env python3
"""Install pinned dependencies into an app-local venv; expose vendored CLI there."""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Python 3.11 or newer")
    parser.add_argument("--env-dir", type=Path, default=ROOT / ".tools/cli")
    parser.add_argument("--with-pyinstaller", action="store_true", help="Install the pinned macOS release builder")
    args = parser.parse_args()
    subprocess.run([args.python, "-c", "import sys; assert sys.version_info >= (3,11), 'Python >=3.11 required'"], check=True)
    environment = args.env_dir.resolve()
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.exists():
        subprocess.run([args.python, "-m", "venv", str(environment)], check=True)
    command = [str(python), "-m", "pip", "--cache-dir", str(ROOT / ".tools/pip-cache"),
               "install", "--only-binary=:all:", "-r", str(ROOT / "vendor/requirements-cli.txt")]
    if args.with_pyinstaller:
        command.append("PyInstaller==6.22.3")
    subprocess.run(command, check=True)
    site = subprocess.check_output([str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip()
    Path(site, "cyberboard-vendor.pth").write_text(str(ROOT / "vendor/cyberboard-cli") + "\n", encoding="utf-8")
    subprocess.run([str(python), "-m", "cyberboard.cli", "--version"], check=True)
    print("Private CLI interpreter:", python)
    print("Run:", python, "-m cyberboard.cli <arguments>")


if __name__ == "__main__":
    main()
