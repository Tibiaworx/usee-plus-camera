"""
Hybrid streamer: 05 once, then read continuously; poke 06 on stall.
Fast + flushed. Assembles JPEGs and reports. Run with:  python -u stream_v2.py
"""
import os, sys, time
import usb.core, usb.util, libusb_package

VID, PID = 0x2CE3, 0x3828
INTF, ALT = 1, 1
EP_OUT, EP_IN = 0x01, 0x81
HERE = os.path.dirname(os.path.abspath(__file__))
MFI = bytes([0xFF,0x55,0xFF,0x55,0xEE,0x10])
C05 = bytes([0xBB,0xAA,0x05,0x00,0x00])
C06 = bytes([0xBB,0xAA,0x06,0x00,0x00])
C08 = bytes([0xBB,0xAA,0x08,0x00,0x00])

def P(*a): print(*a); sys.stdout.flush()

def payload(b):
    # transport header = 5 bytes (AA BB, type, len16); payload then carries a
    # 3-byte per-chunk sub-header before image data -> strip 8 total.
    b = bytes(b)
    if len(b) >= 8 and b[0]==0xAA and b[1]==0xBB:
        return b[8:], b[2]
    return b, None

def main():
    be = libusb_package.get_libusb1_backend()
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=be)
    if dev is None: P("not found"); sys.exit(1)
    usb.util.claim_interface(dev, INTF)
    dev.set_interface_altsetting(interface=INTF, alternate_setting=ALT)
    P("claimed intf1 alt1")

    # handshake
    dev.write(EP_OUT, MFI, timeout=500)
    try: dev.read(EP_IN, 64, timeout=300)
    except usb.core.USBError: pass

    dev.write(EP_OUT, C05, timeout=500)   # latch/start once

    acc = bytearray()
    frames = []
    stalls = 0
    types = {}
    t0 = time.time()
    READS = 250
    for i in range(READS):
        try:
            r = bytes(dev.read(EP_IN, 0x4400, timeout=500))
        except usb.core.USBError:
            r = b""
        if r:
            pl, typ = payload(r)
            types[typ] = types.get(typ, 0) + 1
            acc += pl
            stalls = 0
        else:
            stalls += 1
            # poke: alternate 06 then 05 to see what un-stalls it
            dev.write(EP_OUT, C06 if stalls % 2 else C05, timeout=500)
        # carve any complete frames out of acc
        while True:
            s = acc.find(b"\xff\xd8")
            if s < 0:
                if len(acc) > 4: del acc[:len(acc)-4]  # keep tail for split marker
                break
            e = acc.find(b"\xff\xd9", s)
            if e < 0:
                if s > 0: del acc[:s]
                break
            frames.append(bytes(acc[s:e+2]))
            del acc[:e+2]

    dt = time.time() - t0
    P(f"reads={READS} dt={dt:.1f}s frames={len(frames)} "
      f"fps~{len(frames)/dt:.1f} pkt_types={types}")
    for idx, f in enumerate(frames[:3]):
        open(os.path.join(HERE, f"frame_v2_{idx}.jpg"), "wb").write(f)
        P(f"  frame {idx}: {len(f)} B saved")
    dev.write(EP_OUT, C08, timeout=500)
    usb.util.release_interface(dev, INTF); usb.util.dispose_resources(dev)

    if frames:
        try:
            from PIL import Image; import io
            im = Image.open(io.BytesIO(frames[0])); im.load()
            P(f"DECODED frame0: {im.size} {im.mode}")
        except Exception as e:
            P(f"decode failed: {e}")

if __name__ == "__main__":
    main()
