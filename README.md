# ICE_PLANT_VIEWER
Client-facing viewer for the ICE_PLANT remote monitoring dongle.

## Highlights
- Time-domain plot shows the raw HR1/HR2/MHR samples.
- Spectrogram is a **waterfall**: newest row at the top, moving down with time.
- Live spectrogram rows are plotted **only from live data**; prefilled history is used only to compute the first row so you don't wait for the window to fill.

## Spectrogram Controls
- `Spec Window (s)`: FFT window length (16, 32, 60, 180, 300 seconds). Longer windows give better frequency resolution.
- `Freq Range (Hz)`: Display range (0–0.5, 0–1.0, 0–2.0 Hz).

## Live Prefill Behavior
On connect, the app fetches prior data from the current remote file (based on timestamps) to fill the FFT window. The waterfall display itself starts from the top and only shows rows from live samples.

## macOS Build (PyInstaller)
1. Install build deps:
   - `pip install pyinstaller`
2. Build:
   - `bash scripts/build_macos.sh`
3. Output:
   - `dist/Ice Plant Viewer.app`

The macOS menu bar app name comes from the bundle; the `.app` name here is what will display.

## macOS Installer (DMG, Unsigned)
1. Install `create-dmg`:
   - `brew install create-dmg`
   - If Homebrew link conflicts, run: `brew link --overwrite create-dmg`
2. Build the app (see macOS Build above).
3. Create DMG:
   ```bash
   # If the DMG already exists, delete it first:
   #   rm -f "Ice-Plant-Viewer.dmg"
   create-dmg \
     --volname "Ice Plant Viewer" \
     --window-pos 200 120 \
     --window-size 600 400 \
     --icon-size 100 \
     --icon "Ice Plant Viewer.app" 180 170 \
     --app-drop-link 420 170 \
     "Ice-Plant-Viewer.dmg" \
     "dist/Ice Plant Viewer.app"
   ```

Fallback (simple DMG, no layout):
- `hdiutil create -volname "Ice Plant Viewer" -srcfolder "dist/Ice Plant Viewer.app" -ov -format UDZO "Ice-Plant-Viewer.dmg"`

## Build Artifacts (Git)
Do not commit build outputs:
- `dist/`
- `build/`

If already tracked:
1. `git rm -r --cached dist build`
2. Add to `.gitignore`

## Packaged App Defaults
The packaged app does not persist your personal host/IP in the build. It always starts with the default host in the UI.
