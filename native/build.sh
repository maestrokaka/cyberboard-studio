#!/bin/zsh
set -euo pipefail

native_dir="${0:A:h}"
project_dir="${native_dir:h}"
build_dir="$project_dir/build"
app_dir="$build_dir/Cyberboard Studio.app"
backend_dir="$build_dir/macos-backend/CyberboardBackend"
web_dir="$project_dir/web"
dev_python=""

usage() {
  print 'Usage: native/build.sh [--backend-dir FROZEN-DIRECTORY] [--web-dir WEB-DIRECTORY] [--output APP-PATH] [--dev-python PYTHON-PATH]'
  print 'Release builds require the frozen CyberboardBackend directory; --dev-python enables an explicit source-only development build.'
}
while (( $# > 0 )); do
  case "$1" in
    --backend-dir|--web-dir|--output|--dev-python)
      option="$1"
      (( $# >= 2 )) || { usage; exit 2; }
      case "$option" in
        --backend-dir) backend_dir="${2:A}" ;;
        --web-dir) web_dir="${2:A}" ;;
        --output) app_dir="${2:A}" ;;
        --dev-python) dev_python="${2:A}" ;;
      esac
      shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) print -u2 "Unknown option: $1"; usage; exit 2 ;;
  esac
done

[[ -f "$web_dir/index.html" && -f "$web_dir/data.js" ]] || { print -u2 'Web resources are missing.'; exit 1; }
[[ ( -f "$backend_dir/CyberboardBackend" && -x "$backend_dir/CyberboardBackend" ) || -n "$dev_python" ]] || {
  print -u2 "Frozen backend is missing: $backend_dir/CyberboardBackend"
  print -u2 'Build the macOS runtime first, or use --dev-python for a development build.'
  exit 1
}
[[ -z "$dev_python" || -x "$dev_python" ]] || { print -u2 "Development Python is not executable: $dev_python"; exit 1; }

# Reject forbidden credential routes before building any candidate bundle.
/usr/bin/python3 - "$native_dir/Studio.swift" "$native_dir/MiaoCall.swift" "$native_dir/Companion.swift" <<'PY'
import pathlib, re, sys
source = '\n'.join(pathlib.Path(name).read_text(encoding='utf-8') for name in sys.argv[1:])
for marker in ('SecItem', 'SecKeychain', 'kSec', 'Keychain', 'import Security',
               'legacyCredentialRead', 'readLegacyKey', 'Cyberboard Studio.Kimi'):
    if re.search(r'(?<![A-Za-z0-9_])' + re.escape(marker), source):
        raise SystemExit('System credential interface is forbidden: ' + marker)
PY

# Only sanitized preview assets may enter a distributable .app. Inspect the
# source without modifying it; test fixtures and local records stay outside.
/usr/bin/python3 - "$web_dir/data.js" <<'PY'
import json, pathlib, sys
source = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
prefix = 'window.STUDIO_DATA='
if not source.startswith(prefix) or not source.rstrip().endswith(';'):
    raise SystemExit('Unexpected preview-data format.')
data = json.loads(source[len(prefix):].rstrip().removesuffix(';'))
snapshot = data.get('snapshot') or {}
if data.get('baseConfig') is not None or any(value not in (None, False, '') for value in snapshot.values()):
    raise SystemExit('Refusing to bundle personal device data. Regenerate the release preview assets first.')
if any(len(key.get('bindings', [])) > 1 for key in data.get('keyLayout', [])):
    raise SystemExit('Refusing to bundle custom keymap layers. Regenerate the release preview assets first.')
PY

contents_dir="$app_dir/Contents"
mkdir -p "$contents_dir/MacOS" "$contents_dir/Resources" "$build_dir"

# Swift permits one top-level entry file; combine the native modules into an
# ignored build source without changing their reviewable production files.
/bin/cat "$native_dir/Companion.swift" "$native_dir/MiaoCall.swift" "$native_dir/Studio.swift" > "$build_dir/StudioHost.swift"
/usr/bin/xcrun swiftc -O -swift-version 5 -target "$(/usr/bin/uname -m)-apple-macosx13.0" \
  -module-cache-path "$build_dir/swift-module-cache" \
  -framework Cocoa -framework WebKit -framework UniformTypeIdentifiers -framework AVFoundation -framework ApplicationServices \
  "$build_dir/StudioHost.swift" -o "$contents_dir/MacOS/CyberboardStudio"
/usr/bin/python3 - "$contents_dir/MacOS/CyberboardStudio" <<'PY'
import pathlib, subprocess, sys
binary = pathlib.Path(sys.argv[1])
dependencies = subprocess.check_output(['/usr/bin/otool', '-L', str(binary)], text=True)
symbols = subprocess.check_output(['/usr/bin/nm', '-u', str(binary)], text=True)
if 'Security.framework' in dependencies or any(marker in symbols for marker in ('SecItem', 'SecKeychain')):
    raise SystemExit('Packaged host imports a forbidden system credential interface.')
PY
/bin/cp "$native_dir/Info.plist" "$contents_dir/Info.plist"
if [[ -n "$dev_python" ]]; then
  /usr/bin/plutil -insert CyberboardDevelopmentPythonPath -string "$dev_python" "$contents_dir/Info.plist"
fi
/usr/bin/plutil -lint "$contents_dir/Info.plist"

for resource_name in web backend; do
  resource_target="$contents_dir/Resources/$resource_name"
  if [[ -d "$resource_target" ]]; then /bin/rm -rf "$resource_target"; fi
done
/usr/bin/ditto "$web_dir" "$contents_dir/Resources/web"
mkdir -p "$contents_dir/Resources/backend"
if [[ -f "$backend_dir/CyberboardBackend" && -x "$backend_dir/CyberboardBackend" ]]; then
  /usr/bin/ditto "$backend_dir" "$contents_dir/Resources/backend/CyberboardBackend"
fi
if [[ -n "$dev_python" ]]; then
  for module_name in bridge.py kimi_ai.py lighting_recipe.py ai_images.py ai_quality.py speech_input.py keymap_codec.py miao_call.py companion.py; do
    /bin/cp "$project_dir/backend/$module_name" "$contents_dir/Resources/backend/$module_name"
  done
fi

# Generate the approved Dock artwork into the bundle, never into web source.
/usr/bin/xcrun swiftc -O -swift-version 5 -target "$(/usr/bin/uname -m)-apple-macosx13.0" \
  -module-cache-path "$build_dir/swift-module-cache" -framework AppKit \
  "$native_dir/make-icon.swift" -o "$build_dir/make-icon"
"$build_dir/make-icon" \
  "$project_dir/branding/product-icon/cyberboard-studio-approved-am-paw-v10.png" \
  "$build_dir/AppIcon.iconset" \
  "$contents_dir/Resources/web/assets/branding/product-icon/cyberboard-studio-approved-am-paw-v10.png"
/usr/bin/iconutil --convert icns --output "$contents_dir/Resources/AppIcon.icns" "$build_dir/AppIcon.iconset"

# Remove preview-source caches, preserving every frozen-runtime file byte.
/usr/bin/find "$contents_dir/Resources/web" \( -name __pycache__ -o -name .DS_Store -o -name '*.pyc' \) -prune -exec /bin/rm -rf {} +
/usr/bin/codesign --force --deep --sign - "$app_dir"
/usr/bin/codesign --verify --deep --strict "$app_dir"
print "Built: $app_dir"
