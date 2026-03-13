#!/usr/bin/env python3
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_DIR = os.path.abspath(os.getcwd())
APPLE_ICON_PATH = os.path.join(PROJECT_DIR, "assets", "ice-plant-apple.icns")
DEFAULT_ICON_PATH = os.path.join(PROJECT_DIR, "assets", "ice_plant.icns")
WINDOWS_ICON_PATH = os.path.join(PROJECT_DIR, "assets", "ice_plant.ico")

if sys.platform == "darwin":
    ICON_PATH = APPLE_ICON_PATH if os.path.exists(APPLE_ICON_PATH) else DEFAULT_ICON_PATH
    ICON_BASENAME = "ice-plant-apple" if os.path.exists(APPLE_ICON_PATH) else "ice_plant"
elif sys.platform.startswith("win") and os.path.exists(WINDOWS_ICON_PATH):
    ICON_PATH = WINDOWS_ICON_PATH
    ICON_BASENAME = "ice_plant"
else:
    ICON_PATH = None
    ICON_BASENAME = None

hiddenimports = []
hiddenimports += collect_submodules("paramiko")
hiddenimports += collect_submodules("PySide6")
hiddenimports += collect_submodules("matplotlib")
hiddenimports += collect_submodules("numpy")

datas = []
datas += collect_data_files("matplotlib", include_py_files=True)
if os.path.exists(WINDOWS_ICON_PATH):
    datas.append((WINDOWS_ICON_PATH, "assets"))
if os.path.exists(APPLE_ICON_PATH):
    datas.append((APPLE_ICON_PATH, "assets"))
elif os.path.exists(DEFAULT_ICON_PATH):
    datas.append((DEFAULT_ICON_PATH, "assets"))

a = Analysis(
    ["ice_plant_viewer.py"],
    pathex=[PROJECT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ice Plant Viewer",
    icon=ICON_PATH,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="Ice Plant Viewer",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Ice Plant Viewer.app",
        icon=ICON_PATH,
        bundle_identifier="com.ice-plant.viewer",
        info_plist={
            "CFBundleIconFile": ICON_BASENAME,
        },
    )
