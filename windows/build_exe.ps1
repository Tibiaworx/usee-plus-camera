# Build a standalone UseePlusCamera.exe (no Python needed to run the result).
# Requires: pip install -r requirements.txt pyinstaller
# Output: dist\UseePlusCamera.exe
Set-Location $PSScriptRoot
python -m PyInstaller --noconfirm --onefile --name UseePlusCamera `
    --collect-all libusb_package `
    --collect-submodules usb1 `
    usee_app.py
Write-Host "`nDone -> dist\UseePlusCamera.exe"
