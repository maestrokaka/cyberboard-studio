"""CI-only test of the official Windows CLI and the real setup-only protocol.

The workflow installs the official CLI into its disposable runner account.
This test uses a fresh Codex profile, performs no login and creates no model
turn. It never opens authentication files or invokes task tools.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from codex_runtime import locate
from codex_connection import Connection, run


def main():
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Run only on the disposable Windows GitHub Actions runner; no local account is tested")
    runtime = Path(locate())
    expected = Path(os.environ["LOCALAPPDATA"]) / "Programs/OpenAI/Codex/bin/codex.exe"
    if runtime.resolve() != expected.resolve():
        raise AssertionError("Automatic discovery did not select the official current-user installation")
    version = subprocess.run([str(runtime), "--version"], capture_output=True, text=True, check=True, timeout=15)
    if not version.stdout.strip().startswith("codex-cli "):
        raise AssertionError("The discovered executable did not identify itself as the Codex CLI")
    events, methods = [], []
    original_request = Connection.request

    async def setup_request(self, method, params, *args, **kwargs):
        if method not in {"initialize", "account/read"}:
            raise AssertionError("The check attempted a login or task operation: " + method)
        methods.append(method)
        return await original_request(self, method, params, *args, **kwargs)

    before = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="miaocall-codex-setup-") as fixture:
        root = Path(fixture)
        profile, workspace = root / "codex-profile", root / "workspace"
        profile.mkdir()
        workspace.mkdir()
        # This is the official profile-directory override for a new test account
        # context, not a copied login or a read of the runner's default profile.
        environment = dict(os.environ)
        environment["CODEX_HOME"] = str(profile)
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
            environment.pop(key, None)
        try:
            os.chdir(workspace)
            with patch.dict(os.environ, environment, clear=True), patch.object(Connection, "request", setup_request):
                result = run({"mode": "check"}, events.append, None, state_dir=root / "studio-state")
        finally:
            os.chdir(before)
        if result.get("installed") is not True or result.get("protocolReady") is not True:
            raise AssertionError("Official setup protocol failed: " + json.dumps(result, ensure_ascii=False))
        if result.get("authenticated") is not False:
            raise AssertionError("A fresh isolated profile unexpectedly had a signed-in account")
        if methods != ["initialize", "account/read"]:
            raise AssertionError("Connection check did not use the expected setup-only protocol")
        if events:
            raise AssertionError("Read-only detection unexpectedly requested browser login or a task event")
    print("PASS official Windows CLI installed and automatically found without refreshing PATH")
    print("PASS real app-server initialize/account/read: installed=true protocolReady=true authenticated=false; no login, model turn or task tools")
    print("Official CLI version: " + version.stdout.strip())


if __name__ == "__main__":
    main()
