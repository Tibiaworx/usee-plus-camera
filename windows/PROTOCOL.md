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

## CONFIRMED ON HARDWARE (working Windows capture)
- Stream = 640x480 JPEG frames, ~2-3 fps. Decoded real images via WinUSB/pyusb.
- Each IN packet is **944 bytes** and does NOT coalesce (device short-packets every 944).
- **Per-packet layout: 8-byte transport header + 4-byte rotating tag + JPEG data.**
  - Header: `AA BB 07 [len16=0x03AB] 00 00 00` (device->host magic is `AA BB`, type 0x07).
  - 4-byte tag cycles through 4 values: `F9 BB C6 94` (frame-start, followed by `FF D8`),
    then `01 80 14 F6`, `60 33 30 24`, `22 FF 24 E8`, repeating.
  - **Strip 12 bytes from every packet, concatenate, carve FF D8..FF D9 = one JPEG.**
    (Verified: FF D8 sits at exactly offset 12; strip=13 destroys the marker.)
- Pull cadence that works: send `BB AA 05` ONCE, then read IN continuously; if a read
  times out, poke with `BB AA 06` (or `05`) to resume. Device streams packets back-to-back.
- Send `BB AA 08` to stop.

## Vendor command framing (OUT, host->device)
Little-endian header: `[0]=0xBB [1]=0xAA [2]=CID [3..4]=length(LE) [5..]=payload`

| CID  | Meaning                        | OUT bytes                         |
|------|--------------------------------|-----------------------------------|
| 0x05 | open / connect stream          | `BB AA 05 00 00`                  |
| 0x06 | stream-data / next-frame ack   | `BB AA 06 00 00`                  |
| 0x08 | stop / disconnect stream       | `BB AA 08 00 00`                  |
| 0x0B | switch camera / get info       | `BB AA 0B 00 02 01 <cam> <res> 00`|

MFi wake probe: OUT `FF 55 FF 55 EE 10`, expected IN `BB AA 05 00 00 10`.

## Init & preview sequence
1. Open device, claim interface 1, `set_interface_altsetting(alt=1)`. Endpoints: OUT 0x01 / IN 0x81.
2. MFi probe (`testmfiusb`): read 6 bytes IN, write `FF 55 FF 55 EE 10` OUT (wake/probe).
3. `begincmd()` (native session open).
4. Open-stream loop (<=10 tries): write `BB AA 05 00 00`; read up to 0x4400; if reply `buf[2]==0x05`,
   then write `BB AA 06 00 00`; read; success when reply `buf[2]==0x06`.
5. Native `CallBackStart` thread then continuously pulls frames (repeated 05/06 pulls) and
   reassembles vendor "pro" packets by `pro->length` into complete frames.

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

## Frame rate (measured)
- Device is self-paced: ~90 ms median between frames (~11 fps ceiling), dragged to
  ~8 fps average by occasional ~600 ms stalls. Likely exposure-limited (dim scene).
- Throughput is only ~0.06 MB/s (0.15% of USB high-speed) -> NOT bandwidth-limited.
- 16 vs 64 in-flight async transfers give identical fps -> NOT host/transfer-limited.
- Sync one-read-at-a-time driver = ~4 fps; async (>=16 in-flight) = ~8 fps (2x), which
  is the practical device ceiling in current lighting. See `useeplus_camera_async.py`.

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

## Still-unknown (needs live capture or Ghidra on libOtgCamera.so `datatransfer`/`handle_pro`)
1. Exact multi-packet frame reassembly (is byte[3..4] payload len or total; continuation scheme).
2. GET_ALLINFO exact request bytes.
3. Steady-state pull cadence (one `BB AA 06` per frame vs auto-stream).
4. Meaning of the CBW identity commands (checkid/getlic) — model/license gating.
