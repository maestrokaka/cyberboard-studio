"""Find official native Codex installations. Never load account or credential files."""
from __future__ import annotations
import os
from pathlib import Path
import shutil

MAC_LOCATIONS = (
 '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',
 '/Applications/Codex.app/Contents/Resources/codex',
 '/Applications/Codex.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',
)

def candidates(*, windows=None, environ=None, which=None):
    windows = os.name == 'nt' if windows is None else windows
    env = os.environ if environ is None else environ
    lookup = shutil.which if which is None else which
    result = []
    if windows:
        local, roaming, home = (env.get(k) for k in ('LOCALAPPDATA','APPDATA','USERPROFILE'))
        if local:
            result += [Path(local)/'Programs/OpenAI/Codex/bin/codex.exe', Path(local)/'Programs/Codex/resources/codex.exe']
        if home: result += [Path(home)/'.local/bin/codex.exe']
        # npm's .cmd/.ps1 shims are not executable processes. Use its native
        # binary and keep every neighbouring runtime/helper in place.
        npm_roots = [Path(roaming)/'npm/node_modules/@openai/codex'] if roaming else []
        found = lookup('codex.exe') or lookup('codex')
        if found:
            path = Path(found)
            if path.suffix.lower()=='.exe': result.append(path)
            else: npm_roots.append(path.parent/'node_modules/@openai/codex')
        for root in npm_roots:
            for triple, package in [('x86_64-pc-windows-msvc','codex-win32-x64'),('aarch64-pc-windows-msvc','codex-win32-arm64')]:
                result += [root/'vendor'/triple/'codex/codex.exe', root/'node_modules/@openai'/package/'vendor'/triple/'codex/codex.exe', root.parent/package/'vendor'/triple/'codex/codex.exe']
    else:
        result += [Path(p) for p in MAC_LOCATIONS]
        found = lookup('codex')
        if found: result.append(Path(found))
    return list(dict.fromkeys(result))

def locate(selected=None, **options):
    windows = options.get('windows', os.name=='nt')
    if selected:
        if not isinstance(selected,str) or len(selected)>4096 or not Path(selected).is_absolute(): raise FileNotFoundError('invalid Codex path')
        paths=[Path(selected)]
    else: paths=candidates(**options)
    for path in paths:
        if (not windows or path.suffix.lower()=='.exe') and path.is_file() and os.access(path,os.X_OK):
            return str(path.resolve())
    raise FileNotFoundError('native Codex not found')
