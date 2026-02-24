Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

$os = $env:OS
if ($os -ne "Windows_NT") {
  Write-Error "This script must be run on Windows. PyInstaller does not cross-compile from macOS/Linux."
  exit 1
}

pyinstaller --clean -y ice_plant_viewer.spec
Write-Host "Build complete: dist/"
