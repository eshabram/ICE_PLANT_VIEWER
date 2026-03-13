# ICE_PLANT_VIEWER
Client-facing viewer for the ICE_PLANT remote monitoring dongle.

## Highlights
- Time-domain plot shows the raw HR1/HR2/MHR samples.
- TOCO tab shows uterine activity over time on a dedicated plot.

## TOCO Tab
- Displays uterine activity (TOCO) as a filled trace.
- Uses the same time window as the time-domain plot.
- Toggle TOCO visibility using the `TOCO` checkbox.

## Corometrics RS-232 Cable Notes
A custom cable was constructed to interface the Corometrics 250cx communication port (J109/J110/J111) to the Raspberry Pi Zero 2 W via a MAX3232 RS-232 level converter.

The Corometrics communication ports are RJ-11 (6P6C) RS-232C interfaces. A RJ-11 to bare-wire breakout cable is used on the monitor side. The bare wires are spliced to a DB9 male to bare-wire cable, which mates with the DB9 female connector on the MAX3232 module.

Only the required RS-232 signals are connected:
- RJ-11 pin 5 (TXD) → DB9 pin 2 (RXD)
- RJ-11 pin 2 (RXD) → DB9 pin 3 (TXD)
- RJ-11 pin 3 or 4 (GND) → DB9 pin 5 (GND)

Optional hardware flow control lines were also wired:
- RJ-11 pin 1 (RTS) → DB9 pin 7 (RTS)
- RJ-11 pin 6 (CTS) → DB9 pin 8 (CTS)

Unused DB9 pins (1, 4, 6, 9) are left unconnected.

The DB9 male connector plugs directly into the MAX3232 board, which performs RS-232 to 3.3V TTL conversion. The TTL side of the MAX3232 connects to the Raspberry Pi UART (GPIO14/TXD0, GPIO15/RXD0, 3.3V, and GND).

## MacOS Build And Release
Build the macOS app bundle only:
```bash
bash scripts/build_macos.sh
```

Create a full macOS release:
- builds `dist/Ice Plant Viewer.app`
- then creates a versioned `.dmg`

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

Script split:
- `scripts/build_macos.sh`: builds the `.app` only
- `scripts/release_macos.sh`: builds the `.app` and packages the `.dmg`

The macOS menu bar app name comes from the bundle; the `.app` name here is what will display.

## Windows Build And Release
Build the Windows app from Git Bash, MSYS2, or another bash environment on a Windows machine:
```bash
bash scripts/build_windows.sh
```

Create Windows release artifacts from bash on Windows:
- builds `dist/Ice Plant Viewer/`
- then packages release artifacts

```bash
bash scripts/release_windows.sh
```

Options:
- `--no-bump` to keep the current version
- `--version X.Y.Z` to set an explicit version

Release output:
- Always creates `dist/releases/Ice-Plant-Viewer-X.Y.Z-windows.zip`
- Also creates `dist/releases/Ice-Plant-Viewer-X.Y.Z-setup.exe` when Inno Setup 6 is installed

Script split:
- `scripts/build_windows.sh`: builds the app directory only
- `scripts/release_windows.sh`: builds the app directory and packages the ZIP, plus the `.exe` installer when Inno Setup is available

Windows prerequisites:
- Run the scripts on Windows; PyInstaller does not cross-compile from macOS/Linux
- `pyinstaller` available in the active environment
- Optional: Inno Setup 6 installed for the `.exe` installer (`ISCC.exe`)

## Versioning
We use semantic versioning: `MAJOR.MINOR.PATCH`.
- Increment `MAJOR` for breaking changes
- Increment `MINOR` for new features
- Increment `PATCH` for fixes and small changes

## GitHub Releases
Pushing a git tag like `v0.2.0` triggers the GitHub Actions release workflow in [`.github/workflows/release.yml`](/Users/elliotshabram/repos/ICE_PLANT_VIEWER/.github/workflows/release.yml).

That workflow:
- creates or updates the GitHub Release for the tag
- builds the macOS release and uploads the `.dmg`
- builds the Windows release and uploads the ZIP and, when available, the `.exe` installer

Example:
```bash
git tag v0.2.0
git push origin v0.2.0
```
