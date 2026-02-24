#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PY="${ROOT_DIR}/ice_plant_viewer.py"
APP_NAME="Ice Plant Viewer"
APP_BUNDLE="${ROOT_DIR}/dist/${APP_NAME}.app"

NO_BUMP=0
SET_VERSION=""

cd "$ROOT_DIR"

usage() {
  cat <<EOF
Usage: scripts/release_macos.sh [--no-bump] [--version X.Y.Z]

Options:
  --no-bump         Do not change version; use current APP_VERSION.
  --version X.Y.Z   Set version explicitly.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-bump)
      NO_BUMP=1
      shift
      ;;
    --version)
      SET_VERSION="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

current_version="$(
  python - "$APP_PY" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', text, re.M)
if not m:
    raise SystemExit("APP_VERSION not found")
print(m.group(1))
PY
)"

new_version="$current_version"
if [[ -n "$SET_VERSION" ]]; then
  new_version="$SET_VERSION"
elif [[ "$NO_BUMP" -eq 0 ]]; then
  IFS='.' read -r major minor patch <<<"$current_version"
  patch="${patch:-0}"
  patch=$((patch + 1))
  new_version="${major}.${minor}.${patch}"
fi

if [[ "$new_version" != "$current_version" ]]; then
  python - "$APP_PY" "$new_version" <<'PY'
import re, sys
path, version = sys.argv[1], sys.argv[2]
text = open(path, "r", encoding="utf-8").read()
text, count = re.subn(r'^APP_VERSION\s*=\s*"([^"]+)"', f'APP_VERSION = "{version}"', text, flags=re.M)
if count != 1:
    raise SystemExit("Failed to update APP_VERSION")
open(path, "w", encoding="utf-8").write(text)
PY
  echo "Updated version: ${current_version} -> ${new_version}"
else
  echo "Version unchanged: ${current_version}"
fi

DMG_NAME="Ice-Plant-Viewer-${new_version}.dmg"
DMG_PATH="${ROOT_DIR}/${DMG_NAME}"

bash "${ROOT_DIR}/scripts/build_macos.sh"

rm -f "${ROOT_DIR}"/*.dmg
rm -f "${ROOT_DIR}"/rw.*.dmg
rm -f "${DMG_PATH}"

TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT
export TMPDIR

create-dmg \
  --volname "${APP_NAME}" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "${APP_NAME}.app" 180 170 \
  --app-drop-link 420 170 \
  "${DMG_PATH}" \
  "${APP_BUNDLE}"

echo "Release artifacts:"
echo "  ${APP_BUNDLE}"
echo "  ${DMG_PATH}"
