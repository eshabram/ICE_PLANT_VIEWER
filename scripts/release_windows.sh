#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_PY="${ROOT_DIR}/ice_plant_viewer.py"
APP_NAME="Ice Plant Viewer"
DIST_DIR="${ROOT_DIR}/dist/${APP_NAME}"
RELEASE_DIR="${ROOT_DIR}/dist/releases"
INSTALLER_SCRIPT="${ROOT_DIR}/scripts/windows_installer.iss"

NO_BUMP=0
SET_VERSION=""

usage() {
  cat <<EOF
Usage: scripts/release_windows.sh [--no-bump] [--version X.Y.Z]

Options:
  --no-bump         Do not change version; use current APP_VERSION.
  --version X.Y.Z   Set version explicitly.
EOF
}

case "${OS:-}" in
  Windows_NT) ;;
  *)
    case "$(uname -s)" in
      MINGW*|MSYS*|CYGWIN*) ;;
      *)
        echo "This script must be run on Windows." >&2
        exit 1
        ;;
    esac
    ;;
esac

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
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

current_version="$(
  python - "$APP_PY" <<'PY'
import re
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', text, re.M)
if not match:
    raise SystemExit("APP_VERSION not found")
print(match.group(1))
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
import re
import sys

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

bash "${ROOT_DIR}/scripts/build_windows.sh"

if [[ ! -d "$DIST_DIR" ]]; then
  echo "Expected build output not found: ${DIST_DIR}" >&2
  exit 1
fi

mkdir -p "$RELEASE_DIR"

ZIP_NAME="Ice-Plant-Viewer-${new_version}-windows.zip"
ZIP_PATH="${RELEASE_DIR}/${ZIP_NAME}"
INSTALLER_PATH="${RELEASE_DIR}/Ice-Plant-Viewer-${new_version}-setup.exe"

rm -f "$ZIP_PATH" "$INSTALLER_PATH"

python - "$DIST_DIR" "$ZIP_PATH" <<'PY'
import os
import sys
import zipfile

source_dir, zip_path = sys.argv[1], sys.argv[2]
root_dir = os.path.dirname(source_dir)

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for current_root, _, files in os.walk(source_dir):
        for name in files:
            path = os.path.join(current_root, name)
            arcname = os.path.relpath(path, root_dir)
            zf.write(path, arcname)
PY

ISCC_BIN="$(command -v ISCC.exe || command -v iscc || true)"
if [[ -z "$ISCC_BIN" ]]; then
  for candidate in \
    "/c/Program Files (x86)/Inno Setup 6/ISCC.exe" \
    "/c/Program Files/Inno Setup 6/ISCC.exe"
  do
    if [[ -x "$candidate" ]]; then
      ISCC_BIN="$candidate"
      break
    fi
  done
fi

if [[ -n "$ISCC_BIN" ]]; then
  "$ISCC_BIN" \
    "/DMyAppVersion=${new_version}" \
    "/DMyAppSourceDir=${DIST_DIR}" \
    "/DMyAppOutputDir=${RELEASE_DIR}" \
    "$INSTALLER_SCRIPT"
  echo "Installer created: ${INSTALLER_PATH}"
else
  echo "Inno Setup not found; skipping installer build and keeping ZIP artifact only."
fi

echo "Release artifacts:"
echo "  ${ZIP_PATH}"
if [[ -f "$INSTALLER_PATH" ]]; then
  echo "  ${INSTALLER_PATH}"
fi
