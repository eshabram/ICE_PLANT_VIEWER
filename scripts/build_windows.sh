#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

case "${OS:-}" in
  Windows_NT) ;;
  *)
    case "$(uname -s)" in
      MINGW*|MSYS*|CYGWIN*) ;;
      *)
        echo "This script must be run on Windows. PyInstaller does not cross-compile from macOS/Linux." >&2
        exit 1
        ;;
    esac
    ;;
esac

pyinstaller --clean -y ice_plant_viewer.spec
echo "Build complete: dist/Ice Plant Viewer/"
