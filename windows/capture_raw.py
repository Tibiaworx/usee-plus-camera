"""Capture raw reads to disk AND dissect framing. python -u capture_raw.py"""
import os, sys, pickle, time
import usb.core, usb.util, libusb_package
VID, PID = 0x2CE3, 0x3828
EP_OUT, EP_IN = 0x01, 0x81
HERE = os.path.dirname(os.path.abspath(__file__))
MFI=bytes([0xFF,0x55,0xFF,0x55,0xEE,0x10]); C05=bytes([0xBB,0xAA,0x05,0,0]); C06=bytes([0xBB,0xAA,0x06,0,0]); C08=bytes([0xBB,0xAA,0x08,0,0])
def P(*a): print(*a); sys.stdout.flush()

be=libusb_package.get_libusb1_backend()
dev=usb.core.find(idVendor=VID,idProduct=PID,backend=be)
usb.util.claim_interface(dev,1); dev.set_interface_altsetting(interface=1,alternate_setting=1)
dev.write(EP_OUT,MFI,timeout=500)
try: dev.read(EP_IN,64,timeout=300)
except usb.core.USBError: pass
dev.write(EP_OUT,C05,timeout=500)
reads=[]; stalls=0
for i in range(90):
    try: r=bytes(dev.read(EP_IN,0x4400,timeout=500))
    except usb.core.USBError: r=b""
    reads.append(r)
    if r: stalls=0
    else:
        stalls+=1; dev.write(EP_OUT, C06 if stalls%2 else C05, timeout=500)
dev.write(EP_OUT,C08,timeout=500)
usb.util.release_interface(dev,1); usb.util.dispose_resources(dev)
pickle.dump(reads, open(os.path.join(HERE,"reads.pkl"),"wb"))

# ---- dissect ----
sizes=[len(r) for r in reads if r]
P(f"captured {len(reads)} reads, {sum(1 for r in reads if r)} with data")
from collections import Counter
P("read-size distribution:", dict(Counter(sizes)))
P("\nfirst 16 bytes of first 12 data reads:")
shown=0
for r in reads:
    if not r: continue
    P(f"  len={len(r):5d}: {' '.join(f'{x:02X}' for x in r[:16])}")
    shown+=1
    if shown>=12: break

concat=b"".join(reads)
def all_off(pat):
    o,i=[],0
    while True:
        j=concat.find(pat,i)
        if j<0: break
        o.append(j); i=j+1
    return o
soi=all_off(b"\xff\xd8"); eoi=all_off(b"\xff\xd9"); hdr=all_off(b"\xaa\xbb")
P(f"\nconcat len={len(concat)}")
P(f"AA BB headers: {len(hdr)}  first gaps: {[hdr[i+1]-hdr[i] for i in range(min(8,len(hdr)-1))]}")
P(f"SOI(FFD8) count={len(soi)} first={soi[:5]}")
P(f"EOI(FFD9) count={len(eoi)} first={eoi[:5]}")
# For the first full frame: bytes from first SOI to first EOI after it
if soi and eoi:
    s=soi[0]; e=next((x for x in eoi if x>s), None)
    if e:
        span=concat[s:e+2]
        # how many AA BB headers fall INSIDE the jpeg span?
        inside=[h for h in hdr if s< h <e]
        P(f"\nfirst frame span {s}..{e+2} = {len(span)} bytes, "
          f"AA BB headers inside span: {len(inside)}")
        P(f"  -> if >0, reads coalesce multiple packets; must re-split per AA BB")
