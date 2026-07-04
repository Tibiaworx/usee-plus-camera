"""
Find the per-frame metadata bytes (hardware button + tilt angle).

The frame-start packet looks like:
    AA BB 07 AB 03 | 00 00 00 | F9 BB C6 94 | FF D8 ...(JPEG)
    [transport hdr] [ ?bytes ] [  4-byte tag] [ SOI ]
The button/angle must live in the '?bytes' or the 4-byte tag (they're the only
non-JPEG per-frame fields). This runs 3 phases and diffs those header bytes.

You will be prompted. Follow the on-screen instructions:
  Phase 1: hold camera STILL, do NOT touch the button
  Phase 2: PRESS AND HOLD the hardware button
  Phase 3: release button, slowly TILT / ROTATE the camera in all directions
"""
import sys, time
import usb.core, usb.util, libusb_package

VID, PID = 0x2CE3, 0x3828
EP_OUT, EP_IN = 0x01, 0x81
MFI=bytes([0xFF,0x55,0xFF,0x55,0xEE,0x10]); C05=bytes([0xBB,0xAA,0x05,0,0]); C08=bytes([0xBB,0xAA,0x08,0,0])
NBYTES = 12   # capture bytes [0:12] of each frame-start packet (the header, pre-JPEG)

def P(*a): print(*a); sys.stdout.flush()

be=libusb_package.get_libusb1_backend()
dev=usb.core.find(idVendor=VID,idProduct=PID,backend=be)
if dev is None: P("camera not found / another program has it open"); sys.exit(1)
usb.util.claim_interface(dev,1); dev.set_interface_altsetting(interface=1,alternate_setting=1)
dev.write(EP_OUT,MFI,timeout=500)
try: dev.read(EP_IN,64,timeout=300)
except usb.core.USBError: pass
dev.write(EP_OUT,C05,timeout=500)

def read(to=400):
    try: return bytes(dev.read(EP_IN,0x4400,timeout=to))
    except usb.core.USBError: return b""

def capture(seconds):
    """Collect header bytes of every frame-start packet (one containing FF D8)."""
    rows=[]; end=time.time()+seconds
    while time.time()<end:
        r=read()
        if len(r)>=NBYTES and r[0]==0xAA and r[1]==0xBB and r.find(b"\xff\xd8")==12:
            rows.append(r[:NBYTES])
    return rows

def countdown(msg, secs=3):
    for s in range(secs,0,-1):
        P(f"  {msg} ... starting in {s}"); time.sleep(1)

phases={}
for name,instr in (("STILL","Hold camera STILL, do NOT touch the button"),
                   ("BUTTON","PRESS AND HOLD the hardware button NOW"),
                   ("TILT","Release button; slowly TILT/ROTATE the camera")):
    P(f"\n=== PHASE {name}: {instr} ===")
    countdown(instr, 3)
    P(f"  capturing {name} for 4s...")
    phases[name]=capture(4.0)
    P(f"  got {len(phases[name])} frames")

dev.write(EP_OUT,C08,timeout=300)
usb.util.release_interface(dev,1); usb.util.dispose_resources(dev)

# analyze: distinct values per byte position, per phase
P("\n================ ANALYSIS ================")
P("byte |  STILL values        | BUTTON values        | TILT values")
for i in range(NBYTES):
    def vals(rows):
        s=sorted({row[i] for row in rows})
        return " ".join(f"{v:02X}" for v in s[:8]) + (" .." if len(s)>8 else "")
    still=vals(phases["STILL"]); btn=vals(phases["BUTTON"]); tilt=vals(phases["TILT"])
    tag=""
    if still!=btn: tag+=" <-BUTTON?"
    if len({*[r[i] for r in phases['TILT']]})>2 and tilt!=still: tag+=" <-TILT?"
    P(f" [{i:2d}] | {still:20} | {btn:20} | {tilt:20}{tag}")
P("\nInterpretation: a byte that changes only in BUTTON phase = the shutter button;")
P("a byte (or 4-byte group) that varies continuously in TILT phase = the g-sensor angle.")
