"""
Usee+Plus "supercamera" (2CE3:3828) - Step 2: handshake + capture raw stream.

Exploratory. Sends the documented open-stream commands and DUMPS whatever comes
back so we can see the real frame framing. Tries to carve out a JPEG (FF D8..FF D9)
and save it. Also saves the full raw byte log for offline analysis.

Run:  python handshake_probe.py
Output: written next to this script (dump_raw.bin, frame_00.jpg if a JPEG is found)
"""
import os
import sys
import time
import usb.core
import usb.util
import libusb_package

VID, PID = 0x2CE3, 0x3828
INTF, ALT = 1, 1
EP_OUT, EP_IN = 0x01, 0x81
READ_LEN = 0x4400
HERE = os.path.dirname(os.path.abspath(__file__))

CMD_MFI_PROBE = bytes([0xFF, 0x55, 0xFF, 0x55, 0xEE, 0x10])
CMD_OPEN      = bytes([0xBB, 0xAA, 0x05, 0x00, 0x00])
CMD_STREAM    = bytes([0xBB, 0xAA, 0x06, 0x00, 0x00])
CMD_STOP      = bytes([0xBB, 0xAA, 0x08, 0x00, 0x00])


def hexdump(b, n=48):
    b = bytes(b[:n])
    return " ".join(f"{x:02X}" for x in b) + (" ..." if len(b) >= n else "")


def rd(dev, n=READ_LEN, to=2000, tag=""):
    try:
        data = dev.read(EP_IN, n, timeout=to)
        print(f"  IN  [{tag}] {len(data):5d} B: {hexdump(data)}")
        return bytes(data)
    except usb.core.USBError as e:
        print(f"  IN  [{tag}] <no data: {e.errno} {e.strerror}>")
        return b""


def wr(dev, data, to=1000, tag=""):
    try:
        n = dev.write(EP_OUT, data, timeout=to)
        print(f"  OUT [{tag}] {n} B: {hexdump(data)}")
    except usb.core.USBError as e:
        print(f"  OUT [{tag}] <write failed: {e}>")


def main():
    be = libusb_package.get_libusb1_backend()
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=be)
    if dev is None:
        print("Device not found."); sys.exit(1)

    # We only touch interface 1; leave iAP (intf 0) alone.
    try:
        usb.util.claim_interface(dev, INTF)
    except usb.core.USBError as e:
        print(f"claim_interface failed: {e}"); sys.exit(1)
    dev.set_interface_altsetting(interface=INTF, alternate_setting=ALT)
    print(f"Claimed interface {INTF} alt {ALT}. OUT=0x{EP_OUT:02X} IN=0x{EP_IN:02X}\n")

    raw = bytearray()

    print("[1] MFi wake probe")
    rd(dev, 6, to=500, tag="pre")          # may time out - that's fine
    wr(dev, CMD_MFI_PROBE, tag="mfi")
    raw += rd(dev, 64, to=1000, tag="mfi-reply")

    print("\n[2] open-stream handshake")
    for attempt in range(5):
        wr(dev, CMD_OPEN, tag=f"open#{attempt}")
        r = rd(dev, READ_LEN, to=2000, tag=f"open#{attempt}")
        raw += r
        if len(r) >= 3 and r[2] == 0x05:
            print("  -> got CID 0x05 reply, proceeding to stream")
            break
        time.sleep(0.05)

    print("\n[3] pull stream (BB AA 06) x40, hunting for JPEG")
    for i in range(40):
        wr(dev, CMD_STREAM, tag=f"pull#{i}")
        r = rd(dev, READ_LEN, to=2000, tag=f"pull#{i}")
        raw += r
        if not r:
            time.sleep(0.05)

    # Save raw + try to carve a JPEG
    with open(os.path.join(HERE, "dump_raw.bin"), "wb") as f:
        f.write(raw)
    print(f"\nSaved {len(raw)} raw bytes -> dump_raw.bin")

    soi = raw.find(b"\xff\xd8")
    if soi >= 0:
        eoi = raw.find(b"\xff\xd9", soi)
        print(f"JPEG SOI at {soi}, EOI at {eoi}")
        if eoi > soi:
            jpg = raw[soi:eoi + 2]
            with open(os.path.join(HERE, "frame_00.jpg"), "wb") as f:
                f.write(jpg)
            print(f"  -> carved {len(jpg)} B JPEG -> frame_00.jpg  (open it!)")
    else:
        print("No JPEG SOI (FF D8) seen yet - inspect dump_raw.bin header bytes above.")

    wr(dev, CMD_STOP, tag="stop")
    usb.util.release_interface(dev, INTF)
    usb.util.dispose_resources(dev)


if __name__ == "__main__":
    main()
