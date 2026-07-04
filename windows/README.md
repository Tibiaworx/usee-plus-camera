# Usee+Plus / "supercamera" on Windows

Userspace Windows driver + live viewer for the i4season inspection camera
(USB VID `2CE3` / PID `3828`). No kernel driver — talks to the camera's
`com.useeplus.protocol` interface via WinUSB + libusb.

## One-time setup

1. **Bind WinUSB to Interface 1** with [Zadig](https://zadig.akeo.ie/):
   - Options -> List All Devices
   - Select **`com.useeplus.protocol (Interface 1)`** (USB ID `2CE3 3828`) — NOT the iAP interface
   - Target driver `WinUSB` -> Install/Replace Driver
   - Reversible later via Device Manager -> Uninstall device (delete driver).

2. **Python deps** (Python 3.11+):
   ```
   pip install pyusb libusb-package numpy opencv-python pillow
   ```

## Run

**Standalone (no Python needed):** double-click one of the built exes in `dist\`:
- `UseePlusCameraGUI.exe` - the full **Qt GUI** (recommended): live preview, thumbnail
  gallery, toolbar (snapshot / record / flip / rotate / fullscreen), dark theme.
- `UseePlusCamera.exe` - the lightweight OpenCV-window app.

Build them with `build_exe.ps1` (`pip install -r requirements.txt pyinstaller` first).

**From source:**
```
python usee_gui.py      # Qt GUI (needs PySide6)
python usee_app.py      # OpenCV-window app: HUD, snapshot (s), record (r), hud (h)
python viewer.py        # minimal viewer
```
Snapshots/recordings go to the `captures\` subfolder. In the GUI, `S` = snapshot,
`R` = record, `F11` = fullscreen, and the camera's hardware button auto-snaps.

Only ONE program can hold the camera at a time — close one before starting another.

Or use the driver from your own code (async = faster, ~8 fps):
```python
from useeplus_camera_async import UseePlusCameraAsync
with UseePlusCameraAsync() as cam:
    for frame in cam.frames():   # frame = BGR numpy array (480, 640, 3)
        ...
```

## Files
| File | Purpose |
|------|---------|
| `useeplus_camera.py` | The driver: `UseePlusCamera` class (open/handshake/frames/close) |
| `viewer.py` | Live preview app (fps HUD, snapshot, record) |
| `PROTOCOL.md` | Reverse-engineered USB protocol reference |
| `probe_enumerate.py` | Dumps USB descriptors / confirms endpoints |
| `handshake_probe.py`, `stream_test.py`, `stream_v2.py` | RE / experiment scripts |
| `capture_raw.py`, `analyze_dump.py`, `reconstruct.py` | Framing analysis tools |

## Known facts
- Stream: **640x480 JPEG, ~4 fps** (per-packet USB latency-bound).
- Each 944-byte IN packet = 12-byte header + JPEG data; strip 12, carve `FF D8..FF D9`.
- See `PROTOCOL.md` for the full command set (start/stop, camera+resolution switch).

## Sidecar flags (hardware button / zoom / g-sensor)
Each CID-7 image packet carries a flags byte at **offset 7**. Bit layout (confirmed by
decompiling `libOtgCamera.so` `handle_pro` + `UCallBackHandle1`):

| bit | mask | meaning |
|----|------|---------|
| 0 | 0x01 | `hasg` - g-sensor data present |
| 1 | 0x02 | **`picbutton` - hardware shutter button** |
| 2 | 0x04 | `zoom` |
| 3 | 0x08 | `zoomup` |
| 4 | 0x10 | `zoomdown` |

The driver decodes these on every packet: `cam.button`, `cam.button_presses` (edge
counter the app uses to fire a snapshot), `cam.zoom/zoomup/zoomdown`, `cam.has_gsensor`.
**On this unit only the shutter button is wired** - `hasg` and the zoom bits stay 0, so
tilt auto-rotate is inactive (no accelerometer). Pressing the physical button in the app
saves a `captures\btn_*.png` and flashes a "SHUTTER" overlay.

## Done
- Live 640x480 preview, async ~8 fps (device-limited), auto-reconnect.
- Snapshot + .avi record, **hardware shutter button**, standalone .exe.

## Ideas / TODO
- Nicer GUI (Qt/Tkinter) with a settings panel and a capture gallery.
- Read `getdevinfo` (CID 5) live for firmware/vendor strings + capability bitmap.
