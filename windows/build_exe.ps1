# Build standalone exes (no Python needed to run them).
# Requires: pip install -r requirements.txt pyinstaller
# Output: dist\UseePlusCameraGUI.exe (Qt GUI) and dist\UseePlusCamera.exe (CLI app)
Set-Location $PSScriptRoot

# Qt GUI (recommended)
python -m PyInstaller --noconfirm --onefile --windowed --name UseePlusCameraGUI `
    --collect-all libusb_package --collect-submodules usb1 `
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtNetwork --exclude-module PySide6.Qt3DCore `
    --exclude-module tkinter `
    usee_gui.py

# Lightweight OpenCV-window app
python -m PyInstaller --noconfirm --onefile --name UseePlusCamera `
    --collect-all libusb_package --collect-submodules usb1 `
    usee_app.py

Write-Host "`nDone -> dist\UseePlusCameraGUI.exe  and  dist\UseePlusCamera.exe"
