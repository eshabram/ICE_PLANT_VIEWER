#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

pyinstaller --clean -y ice_plant_viewer.spec
echo "Build complete: dist/Ice Plant Viewer.app"
