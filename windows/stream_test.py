"""
Find the pull cadence that assembles ONE complete JPEG (FF D8 .. FF D9).
Tries several strategies and reports which works. Saves any complete frame.

Run:  python stream_test.py
"""
import os, sys, time
import usb.core, usb.util, libusb_package

VID, PID = 0x2CE3, 0x3828
INTF, ALT = 1, 1
EP_OUT, EP_IN = 0x01, 0x81
HERE = os.path.dirname(os.path.abspath(__file__))

MFI  = bytes([0xFF, 0x55, 0xFF, 0x55, 0xEE, 0x10])
C05  = bytes([0xBB, 0xAA, 0x05, 0x00, 0x00])
C06  = bytes([0xBB, 0xAA, 0x06, 0x00, 0x00])
C08  = bytes([0xBB, 0xAA, 0x08, 0x00, 0x00])


def payload(buf):
    """Strip 5-byte AA BB 07 <len16> transport header; return the payload bytes."""
    b = bytes(buf)
    if len(b) >= 5 and b[0] == 0xAA and b[1] == 0xBB:
        n = b[3] | (b[4] << 8)
        return b[5:5 + n]
    return b


def try_read(dev, to):
    try:
        return bytes(dev.read(EP_IN, 0x4400, timeout=to))
    except usb.core.USBError:
        return b""


def w(dev, data, to=800):
    try:
        dev.write(EP_OUT, data, timeout=to); return True
    except usb.core.USBError:
        return False


def carve(acc):
    """Return first complete JPEG in acc, or None."""
    s = acc.find(b"\xff\xd8")
    if s < 0:
        return None
    e = acc.find(b"\xff\xd9", s)
    if e < 0:
        return None
    return acc[s:e + 2]


def run_strategy(dev, name, steps):
    """steps: list of ('cmd'|'read', value). Loops until a JPEG or budget out."""
    print(f"\n=== strategy: {name} ===")
    acc = bytearray()
    reads = data_reads = 0
    for _ in range(400):
        for kind, val in steps:
            if kind == "cmd":
                w(dev, val)
            else:  # read
                r = try_read(dev, val)
                reads += 1
                if r:
                    data_reads += 1
                    acc += payload(r)
        j = carve(acc)
        if j:
            print(f"  COMPLETE JPEG: {len(j)} bytes after {reads} reads "
                  f"({data_reads} with data), acc={len(acc)}")
            return bytes(j)
    has_soi = "yes" if acc.find(b"\xff\xd8") >= 0 else "no"
    has_eoi = "yes" if acc.find(b"\xff\xd9") >= 0 else "no"
    print(f"  no complete frame. reads={reads} data_reads={data_reads} "
          f"acc={len(acc)} (SOI={has_soi}, EOI={has_eoi})")
    return None


def main():
    be = libusb_package.get_libusb1_backend()
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=be)
    if dev is None:
        print("not found"); sys.exit(1)
    usb.util.claim_interface(dev, INTF)
    dev.set_interface_altsetting(interface=INTF, alternate_setting=ALT)
    w(dev, MFI); try_read(dev, 300)

    strategies = [
        # A: latch once with 05, then keep pulling 06 (long timeout)
        ("05 once, then 06*",       [("cmd", C05)] + [("read", 1500)]
                                     + [("cmd", C06), ("read", 1500)]),
        # B: 05 then read repeatedly WITHOUT resending (auto-stream?)
        ("05 then read-only",       [("cmd", C05)] + [("read", 1200)]),
        # C: alternate 05/06 every step
        ("alternate 05/06",         [("cmd", C05), ("read", 1200),
                                     ("cmd", C06), ("read", 1200)]),
        # D: 06 only, no 05 at all
        ("06 only",                 [("cmd", C06), ("read", 1200)]),
    ]
    got = None
    for name, steps in strategies:
        got = run_strategy(dev, name, steps)
        if got:
            path = os.path.join(HERE, "frame_stream.jpg")
            open(path, "wb").write(got)
            print(f"  saved -> {path}")
            break
        w(dev, C08); time.sleep(0.2)  # reset between strategies

    w(dev, C08)
    usb.util.release_interface(dev, INTF)
    usb.util.dispose_resources(dev)
    if got:
        # validate decode if PIL present
        try:
            from PIL import Image
            import io
            im = Image.open(io.BytesIO(got)); im.load()
            print(f"\nDECODED OK: {im.size} {im.mode}")
        except ImportError:
            print("\n(install pillow to auto-validate: pip install pillow)")
        except Exception as e:
            print(f"\nJPEG did NOT decode cleanly: {e} -> per-chunk sub-headers likely")


if __name__ == "__main__":
    main()
