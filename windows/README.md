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

**Standalone (no Python needed):** double-click `dist\UseePlusCamera.exe`
(build it with `build_exe.ps1`, or `pip install -r requirements.txt pyinstaller` then run that script).

**From source:**
```
python usee_app.py      # main app: auto-reconnect, snapshot, record
python viewer.py        # simpler viewer
```
Keys: `q` quit, `s` snapshot, `r` record .avi, `h` toggle HUD.
Snapshots/recordings go to the `captures\` subfolder.

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

## Metadata (button / tilt) - NOT available over the video interface
The hardware shutter button and g-sensor tilt angle are NOT in the video stream.
Verified: the per-frame packet header holds only a counter + a 4-cycle tag, and the
gap between consecutive JPEGs is 0 bytes. The app reads button/angle via a separate
native `getdevflag`/`getdevinfo` status call inside `libOtgCamera.so`, which is not
yet reverse-engineered. `usee_app.py` has inert hooks (`cam.button`, `cam.angle`)
ready to light up if that RE is done later (would need an ARM64 disassembly of
`libOtgCamera.so` or a longer USB-probing session).

## Done
- Live 640x480 preview, async ~8 fps (device-limited), auto-reconnect.
- Snapshot + .avi record, standalone .exe.

## Ideas / TODO
- Reverse-engineer `getdevflag`/`getdevinfo` in `libOtgCamera.so` to enable the
  hardware button + tilt auto-rotate.
- Nicer GUI (Qt/Tkinter) with a settings panel and a capture gallery.
