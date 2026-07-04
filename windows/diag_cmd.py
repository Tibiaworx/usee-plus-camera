"""Diagnose whether the device ACKs the 0B switch command; dump non-07 packets."""
import sys, time
import usb.core, usb.util, libusb_package
VID, PID = 0x2CE3, 0x3828
EP_OUT, EP_IN = 0x01, 0x81
MFI=bytes([0xFF,0x55,0xFF,0x55,0xEE,0x10]); C05=bytes([0xBB,0xAA,0x05,0,0])
def P(*a): print(*a); sys.stdout.flush()

be=libusb_package.get_libusb1_backend()
dev=usb.core.find(idVendor=VID,idProduct=PID,backend=be)
usb.util.claim_interface(dev,1); dev.set_interface_altsetting(interface=1,alternate_setting=1)
dev.write(EP_OUT,MFI,timeout=500)
try: dev.read(EP_IN,64,timeout=300)
except usb.core.USBError: pass
dev.write(EP_OUT,C05,timeout=500)

def read(to=400):
    try: return bytes(dev.read(EP_IN,0x4400,timeout=to))
    except usb.core.USBError: return b""

def drain_and_report(label, n=80):
    types={}; noln=0
    for _ in range(n):
        r=read()
        if not r: noln+=1; continue
        t = r[2] if len(r)>2 and r[0]==0xAA and r[1]==0xBB else None
        types[t]=types.get(t,0)+1
        if t not in (0x07, None):    # unusual packet - show it
            P(f"  [{label}] non-07 packet type=0x{t:02X}: "
              f"{' '.join(f'{x:02X}' for x in r[:20])}")
    P(f"[{label}] packet types={ {(f'0x{k:02X}' if k is not None else None):v for k,v in types.items()} } empty={noln}")

drain_and_report("baseline")

for cam in (0, 1):
    for res in (0x01, 0x08, 0x20, 0, 1, 2, 3):
        cmd=bytes([0xBB,0xAA,0x0B,0x00,0x02,cam,res,0x00])
        dev.write(EP_OUT,cmd,timeout=500)
        P(f"\n-- sent switch cam={cam} res=0x{res:02X}: {' '.join(f'{x:02X}' for x in cmd)}")
        drain_and_report(f"cam{cam}.res{res:02X}", n=40)

dev.write(EP_OUT,bytes([0xBB,0xAA,0x08,0,0]),timeout=500)
usb.util.release_interface(dev,1); usb.util.dispose_resources(dev)
