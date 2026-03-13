#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

resolve_python() {
  local -a candidate
  for candidate in \
    "python3" \
    "python" \
    "py -3"
  do
    read -r -a parts <<<"$candidate"
    if "${parts[@]}" -c "import sys" >/dev/null 2>&1; then
      PYTHON_BIN=("${parts[@]}")
      return 0
    fi
  done
  echo "Python interpreter not found. Install Python and ensure it is on PATH." >&2
  exit 1
}

resolve_python

"${PYTHON_BIN[@]}" - <<'PY'
from importlib.util import find_spec

required = [
    "PyInstaller",
    "PySide6",
    "matplotlib",
    "numpy",
    "paramiko",
]
missing = [name for name in required if find_spec(name) is None]
if missing:
    raise SystemExit(
        "Missing Python packages for macOS build: "
        + ", ".join(missing)
        + ". Run `pip install -r requirements.txt`."
    )
PY

pyinstaller --clean -y ice_plant_viewer.spec
echo "Build complete: dist/Ice Plant Viewer.app"
