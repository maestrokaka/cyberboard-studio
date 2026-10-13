#!/usr/bin/env python3
"""Compatibility entry point: metadata is already pinned; fetch its exact artifacts."""
from pathlib import Path
import subprocess
import sys

raise SystemExit(subprocess.call([sys.executable, str(Path(__file__).with_name("fetch-runtime.py"))]))
