# Usee+Plus / "supercamera" USB protocol (VID 0x2CE3 / PID 0x3828)

Reverse-engineered from the decompiled `com.i4season.useeplus` APK. This documents the
`com.useeplus.protocol` interface (MI_01) used for video. The `iAP Interface` (MI_00,
Apple MFi) is ignored for Windows.

## Device / USB facts (confirmed on hardware)
- Composite device, class 239/2/1 (Misc/IAD). Mfr "Geek szitman", Product "supercamera".
- **Interface 1 = com.useeplus.protocol**, vendor class 0xFF, subclass 0xF0, protocol 1.
  - **Alt setting 1** carries the endpoints (alt 0 is empty — must `set_interface_altsetting(1)`).
  - **BULK OUT = 0x01**, **BULK IN = 0x81**, wMaxPacketSize 512 (high-speed).
- Access on Windows: WinUSB bound via Zadig -> pyusb/libusb userspace. No kernel driver.

## IN packet layout (device->host) — confirmed by libOtgCamera.so `handle_pro`
Stream = 640x480 JPEG frames, ~8 fps. Each IN packet is 944 bytes and does NOT coalesce
(device short-packets every 944). Fields (offsets are into the raw packet):

```
 off 0..1  : AA BB           magic
 off 2     : CID             5=devinfo, 6=open-stream, 7/10=image, 0x0B=switch-cam
 off 3..4  : length (LE)     "pro->length" = 0x03AB (939) for image packets
 off 5     : per-frame id    changes when a new frame starts (vs continuation)
 off 7     : FLAGS byte      bit0 hasg, bit1 picbutton, bit2 zoom, bit3 zoomup, bit4 zoomdown
 off 8..11 : marker/aux u32
 off 12..  : JPEG data       length = pro->length - 7 = 932 bytes/packet
```

**Reassembly: strip 12 bytes from every packet, concatenate, carve FF D8 .. FF D9 = one
JPEG.** (Verified two ways: FF D8 sits at exactly offset 12 on frame-start packets, and
`handle_pro` calls `mu_camera_data_add(pkt+0xC, pro_len-7)`.)

### Sidecar flags — byte[7] (see `handle_pro` + `UCallBackHandle1`)
| bit | mask | OtgCameraPic field | notes |
|----|------|--------------------|-------|
| 0  | 0x01 | hasg               | g-sensor present (0 on this unit) |
| 1  | 0x02 | picbutton          | **hardware shutter button** (momentary, ~1 packet/press) |
| 2  | 0x04 | zoom               | 0 on this unit |
| 3  | 0x08 | zoomup             | 0 on this unit |
| 4  | 0x10 | zoomdown           | 0 on this unit |

The g-sensor angle is a `float` at `mfi_pic_info+0x0c` (`Setangle`), gated by `hasg`.

### Pull cadence — SETTLED BY WIRE CAPTURE
Send `BB AA 05` **once**, then read IN continuously. Send `BB AA 08` to stop.

**Do NOT send `BB AA 06` while streaming — it kills the stream.** The device
auto-streams after `05`; a hardware USB sniffer shows the Android reference app
sending **zero** host->device packets for an entire 21 s steady-state session
(36,315 IN tokens on ep 0x01, nothing else on any endpoint).

Measured, with pull/no-pull order reversed to rule out ordering effects:

| condition | frames in 12 s |
|-----------|----------------|
| `BB AA 06` every 0.5 s | 2 |
| no pulls               | 86 |
| `BB AA 06` every 0.5 s | 1 |
| no pulls               | 85 |

The old "poke on timeout to resume" advice was actively harmful: a stall caused
read timeouts, the timeouts sent `BB AA 06`, the pull killed the stream, which
caused more timeouts. Recovery belongs in a watchdog that reopens the device,
not in a mid-stream poke.

### byte[5] is a frame counter — SETTLED BY WIRE CAPTURE
`byte[5]` increments by exactly 1 per frame and is constant across all packets
of the same frame (238/250 transitions +1 on a clean reference capture; ~9
packets per run). Use it for authoritative frame boundaries and for detecting
dropped frames, rather than inferring structure from `FF D8`/`FF D9` alone.

## Vendor command framing (OUT, host->device)
Little-endian header: `[0]=0xBB [1]=0xAA [2]=CID [3..4]=length(LE) [5..]=payload`

| CID  | Meaning                        | OUT bytes                         |
|------|--------------------------------|-----------------------------------|
| 0x05 | open / connect stream          | `BB AA 05 00 00`                  |
| 0x06 | stream-data / next-frame ack   | `BB AA 06 00 00`                  |
| 0x08 | stop / disconnect stream       | `BB AA 08 00 00`                  |
| 0x0B | switch camera / get info       | `BB AA 0B 00 02 01 <cam> <res> 00`|

MFi wake probe: OUT `FF 55 FF 55 EE 10` on **endpoint 0x02** (the iAP interface,
MI_00 — NOT the video endpoint). Actual reply observed on the wire is
`FF 55 02 00 EE 10`, **not** the `BB AA 05 00 00 10` previously documented.

## Init & preview sequence — OBSERVED ON THE WIRE
Captured cold (unplug -> replug -> app launch) with a hardware USB sniffer.
The reference app's complete init is six bulk OUT packets; that is all of it:

```
IN    ep 0x02   ff 55 02 00 ee 10          MFi reply
OUT   ep 0x02   ff 55 ff 55 ee 10          MFi probe (iAP interface!)
SETUP ep0       SET_INTERFACE(intf=1, alt=1)
SETUP ep0       GET_DESCRIPTOR(String #5) -> "com.useeplus.protocol"
OUT   ep 0x01   bb aa 05 00 00             open stream
IN    ep 0x01   ...video flows ~155 ms later
```

Corrections to the APK-derived sequence above:
- There is **no `05` -> `06` handshake**. The app sends `05` and nothing more.
- `begincmd()` emits **no wire traffic** - it is purely native bookkeeping.
- There are **no `checkid`/`getlic` identity or license commands** on the wire.
  Nothing gates streaming on model or licence.
- The MFi probe belongs on **ep 0x02**, not the video endpoint. (Sending it on
  ep 0x01 was tested and is harmless to throughput, but it is not what the
  reference does and it injects foreign bytes into the video pipe.)

## Switch camera / resolution (`changeCamera(cam,res)`)
On-wire command (from `OtgCameraApi.changeCamera` smali): write 8 bytes
`BB AA 0B 00 02 <cam> <res> 00` to bulk-OUT, where `<cam>`=byte[5], `<res>`=byte[6]
(bitmask value). The surrounding `begincmd`/`setfilernum(0x0F)`/`checkcmdreturn(0x0B)`
are NATIVE response-handling, not wire traffic.

**HARDWARE RESULT (this unit): resolution switching NOT supported.** Tested every
cam(0/1) x res combination live: the device only ever emits type-0x07 JPEG packets,
NEVER acknowledges CID 0x0B, and the frame size stays 640x480. `changeCamera` is also
dead code in the app (never called by the UI for OTG). Conclusion: this "supercamera"
unit is fixed 640x480 over USB; the multi-resolution code serves other i4season products.

## Frame rate — RE-MEASURED ON THE WIRE

The device is a **metronome at 90 ms/frame**. It is NOT exposure-limited; the
earlier "~600 ms stalls, likely dim scene" conclusion was wrong.

**Android reference app** (hardware sniffer, clean capture, zero PHY/CRC/overflow):

| metric | value |
|--------|-------|
| frame rate | **12.67 fps** |
| inter-frame p50 / p90 / max | **90 / 90 / 90 ms** |
| gaps >150 ms | **0** (over 271 frames / 21.4 s) |

`max == p50`. Not one stall. Throughput ~0.06 MB/s = 0.15% of USB high-speed,
so nothing here is bandwidth-limited.

### The Windows throttle (OPEN ISSUE)
Under WinUSB/libusb the same device, cable and sniffer yields **~7.3 fps** with a
rigid periodic dropout. Characterised precisely:

- **10 frames delivered, ~6 dropped, repeating every 17 frames = 1.53 s**
- stall duration **630 ms**, period **1.53 s ±0.05** - invariant across every
  driver parameter tried (see below)
- `byte[5]` **keeps advancing through the stall** (e.g. 8 -> 15, 25 -> 32): the
  device is still generating frames, it just stops transmitting them
- the last packet before a stall is usually **truncated** (479-586 B instead of
  939) - the device aborts a frame mid-transmission, then goes quiet
- during the stall the device simply **NAKs**; no STALL handshake, no USB error,
  no retry. Host IN-token rate drops 1725/s -> 81/s (xHCI NAK backoff, an
  effect of the silence rather than its cause)
- 11.1 fps native x 10/17 = 6.5 fps, consistent with the ~7.3 fps observed

Ruled out by direct experiment (each tested against the 1.53 s / 630 ms signature):

| hypothesis | result |
|------------|--------|
| JPEG carve pair-loss | fixed; stalls persist |
| `CMD_PULL` poking | removed; stalls persist |
| MFi probe on ep 0x01 vs 0x02 | A/B tested - no effect |
| host not servicing iAP interface | reference app doesn't either - ruled out |
| in-flight transfers (16/8/4/2) | no effect |
| read size (944 / 0x4000 / 0x4400 / 0x8800) | no effect |
| transfer timeout (500 / 2000 / 5000 ms) | no effect |
| host CPU load, JPEG decode | no effect |

Wire behaviour of the two hosts is near-identical (Windows 1726 IN/s vs Android
1697 IN/s, same endpoint, same commands), yet only Windows provokes the abort.
**Root cause unknown.** The remaining untested dimension is fine-grained host
transfer *retirement timing*, which is below this sniffer's resolution and would
need submission-level instrumentation rather than more capture.

Note: keep the transfer timeout comfortably above 630 ms. `timeout_ms=500` is
shorter than the stall, so every stall times out the transfers and throughput
drops to ~5 fps.

## Frames
- **Each frame is a self-contained JPEG** (confirmed: `BitmapFactory.decodeByteArray`,
  `HPDF_Image_LoadJpegImageFromMem`, `*.jpeg` native strings). JPEG SOI=`FF D8`, EOI=`FF D9`.
- A frame may span multiple 0x4400 (17408-byte) bulk reads; reassemble until EOI.
- Per-frame sidecar metadata (`OtgCameraPic`): g-sensor `angle`, hardware shutter `picbutton`,
  `zoom`/`zoomup`/`zoomdown`. Delivered natively; may be embedded in the pro-packet header.
- Resolution bitmask (OtgFirmInfo): 320x240=0x1, 480x480=0x2, 640x480=0x4, 1280x720=0x8,
  1280x960=0x10, 1920x1080=0x20, 1920x1440=0x40, 2592x1944=0x80, 3840x2160=0x100.
- Capabilities: GSENSOR=0x1, MULTI_CAM=0x2, NTC=0x4.

## Timeouts / buffers
- cmd write 1000ms, bulk data read 5000ms, connect/disconnect 100ms.
- read chunk 0x4000 (16384); frame read buffer 0x4400 (17408).

## Resolved by hardware USB capture
1. ~~Exact multi-packet frame reassembly~~ — `byte[3..4]` is the **payload** length
   (0x03AB = 939; JPEG bytes = length - 7 = 932). A frame is ~9 packets of 944 B
   (512 + 432 on the wire). Continuation is signalled by `byte[5]` holding the
   same value; a new frame starts when it increments.
3. ~~Steady-state pull cadence~~ — **auto-stream**. One `BB AA 05`, then read.
   Sending `BB AA 06` mid-stream kills it.
4. ~~CBW identity commands (checkid/getlic)~~ — **not present on the wire at all.**
   No model or licence gating is involved in streaming.

## Still unknown
2. GET_ALLINFO exact request bytes (CID 5 devinfo never observed in a capture —
   the reference app doesn't request it during normal preview).
5. **Root cause of the 1.53 s / 630 ms Windows throttle** (see Frame rate above).
   Everything the driver controls has been eliminated; the device aborts frames
   mid-transmission only under WinUSB/libusb, never under Android.
6. Undocumented `byte[7]` flag bits: values `0x80` and `0x40` observed on a small
   number of packets. The documented map only covers bits 0-4.

## Method note
Findings above marked "wire" came from an inline hardware USB sniffer
(Alex Taradov's LS/FS/HS design) tapping the host<->camera link, with the
Android app used as a known-good control. Captures were rejected unless the
sniffer's info channel reported zero `Hardware buffer overflow` events — an
overflow silently deletes packets and produces convincing but false framing
errors. Two early conclusions had to be retracted for exactly that reason.
