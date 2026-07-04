# Usee+Plus / "supercamera" — Windows driver & app

A userspace **Windows driver and live-viewer app** for the i4season **Usee+Plus**
USB inspection/borescope camera (it enumerates as *"supercamera"* by *"Geek szitman"*,
**USB VID `2CE3` / PID `3828`**). The camera ships with an Android app only and does
nothing on a PC — Windows sees a vendor-specific device it can't drive. This project
reverse-engineers the camera's USB protocol from the Android APK and reimplements it
in Python, so the camera works as a live camera on Windows with **no kernel driver**.

## What it does

- Streams **live 640×480 MJPEG video** from the camera on Windows.
- Runs entirely in **userspace** via WinUSB + libusb — no signed kernel driver.
- Ships as a **standalone `.exe`** (no Python needed) or runs from source.
- **Snapshot** (`s`), **record `.avi`** (`r`), on-screen HUD, and **auto-reconnect**
  when the camera is unplugged/replugged.
- ~8 fps (the device's own hardware ceiling; see notes below).

## How it works (the short version)

The camera is **not** a standard UVC webcam. It exposes a composite USB device with a
vendor interface named `com.useeplus.protocol`. Video is pulled over that interface as
a stream of framed packets, each carrying a slice of a JPEG image:

```
handshake:  FF 55 FF 55 EE 10   then   BB AA 05 00 00   (start stream)
each IN packet (944 B): [12-byte header] + JPEG bytes
                        strip 12, concatenate, carve FF D8 … FF D9 = one JPEG frame
stop:       BB AA 08 00 00
```

Getting raw USB access requires binding the generic **WinUSB** driver to the camera's
data interface once (via [Zadig](https://zadig.akeo.ie/)). Full details, the complete
command set, and the framing are in **[windows/PROTOCOL.md](windows/PROTOCOL.md)**.

## Quick start

1. **One-time:** with [Zadig](https://zadig.akeo.ie/), bind **WinUSB** to
   `com.useeplus.protocol (Interface 1)` (USB ID `2CE3 3828`). Reversible in Device Manager.
2. **Run:** download `UseePlusCamera.exe` from this repo's **Releases** and run it —
   or from source: `pip install -r windows/requirements.txt` then `python windows/usee_app.py`.

Full setup and usage: **[windows/README.md](windows/README.md)**.

## Repository layout

| Path | Contents |
|------|----------|
| `windows/usee_app.py` | Main app: live preview, snapshot, record, auto-reconnect |
| `windows/useeplus_camera_async.py` | High-throughput async USB driver (`UseePlusCameraAsync`) |
| `windows/useeplus_camera.py` | Simple synchronous driver |
| `windows/viewer.py` | Minimal viewer |
| `windows/PROTOCOL.md` | Reverse-engineered USB protocol reference |
| `windows/README.md` | Windows setup & usage |
| `windows/build_exe.ps1` | Build the standalone `.exe` (PyInstaller) |
| `windows/*probe*.py`, `analyze_*`, `reconstruct.py` | The RE / analysis scripts used to crack the protocol |

## Notes & limitations

- **Fixed 640×480.** This unit ignores the resolution-switch command; the multi-resolution
  code in the Android app serves other products in the family.
- **~8 fps is the device ceiling**, not a software limit (throughput is 0.15% of USB
  high-speed; 16 vs 64 in-flight transfers are identical). Likely exposure-limited — a
  brighter scene runs faster.
- **Hardware button & g-sensor tilt are not exposed over the video interface.** They come
  from a separate native status call (`getdevflag`/`getdevinfo`) inside the vendor's
  `libOtgCamera.so`, which isn't reverse-engineered yet. The app has inert hooks
  (`cam.button`, `cam.angle`) ready for when/if that's done.

## Legal

Independent, interoperability-focused reverse engineering of a device the owner
possesses, for the purpose of making it work on a platform the vendor doesn't support.
No vendor code is redistributed here. Trademarks belong to their respective owners.
