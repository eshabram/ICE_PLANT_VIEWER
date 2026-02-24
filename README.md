# ICE_PLANT_VIEWER
Client-facing viewer for the ICE_PLANT remote monitoring dongle.

## Highlights
- Time-domain plot shows the raw HR1/HR2/MHR samples.
- Spectrogram is a **waterfall**: newest row at the top, moving down with time.
- Live spectrogram rows are plotted **only from live data**; prefilled history is used only to compute the first row so you don't wait for the window to fill.

## Spectrogram Controls
- `Spec Window (s)`: FFT window length (16, 32, 60, 180, 300 seconds). Longer windows give better frequency resolution.
- `Freq Range (Hz)`: Display range (0–0.5, 0–1.0, 0–2.0 Hz).

## MacOS Release (App + DMG)
Preferred path (automated, uses create-dmg):
```bash
bash scripts/release_macos.sh
```

Options:
- `--no-bump` to keep the current version
- `--version X.Y.Z` to set an explicit version

Note: create-dmg uses Finder during layout, so it will open a window while building the DMG.

Examples:
```bash
bash scripts/release_macos.sh --no-bump
bash scripts/release_macos.sh --version 0.2.0
```

Manual build/install steps are documented in `scripts/build_macos.sh` and `scripts/release_macos.sh`.
The macOS menu bar app name comes from the bundle; the `.app` name here is what will display.

## Versioning
We use semantic versioning: `MAJOR.MINOR.PATCH`.
- Increment `MAJOR` for breaking changes
- Increment `MINOR` for new features
- Increment `PATCH` for fixes and small changes
