#!/usr/bin/env python3
"""Fetch exact official Windows build artifacts into the ignored app-local cache."""
from __future__ import annotations
import hashlib
import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]
CACHE = APP / ".tools/windows-runtime/downloads"
PYTHON = {"filename": "python-3.12.10-embed-amd64.zip",
    "url": "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
    "sha256": "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(item):
    destination = CACHE / item["filename"]
    if destination.exists() and digest(destination) == item["sha256"]:
        print("Verified cached", item["filename"])
        return
    partial = destination.with_name(destination.name + ".download")
    request = urllib.request.Request(item["url"], headers={"User-Agent": "CyberboardStudio-build/0.1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if digest(partial) != item["sha256"]:
            raise RuntimeError("Official artifact checksum mismatch: " + item["filename"])
        partial.replace(destination)
        print("Downloaded and verified", item["filename"])
    finally:
        partial.unlink(missing_ok=True)


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    fetch(PYTHON)
    for metadata in sorted((HERE / "downloads").glob("*.whl.json")):
        name = metadata.name[:-5]
        value = json.loads(metadata.read_text(encoding="utf-8"))
        artifact = next(item for item in value["urls"] if item["filename"] == name)
        if not artifact["url"].startswith("https://files.pythonhosted.org/"):
            raise RuntimeError("Pinned wheel must use the official PyPI file host")
        fetch({"filename": name, "url": artifact["url"], "sha256": artifact["digests"]["sha256"]})
    print("Build cache:", CACHE)


if __name__ == "__main__":
    main()
