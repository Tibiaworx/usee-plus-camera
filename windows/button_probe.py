"""
Verify the hardware button / zoom bits live in packet byte[7].
Per libOtgCamera.so handle_pro: image packet (CID 7) byte[7] bit layout:
  bit0=hasg  bit1=picbutton  bit2=zoom  bit3=zoomup  bit4=zoomdown

Run it, then PRESS/RELEASE the hardware button repeatedly for ~10 seconds.
"""
import sys, time
import usb.core, usb.util, libusb_package
VID, PID = 0x2CE3, 0x3828
EP_OUT, EP_IN = 0x01, 0x81
MFI=bytes([0xFF,0x55,0xFF,0x55,0xEE,0x10]); C05=bytes([0xBB,0xAA,0x05,0,0]); C08=bytes([0xBB,0xAA,0x08,0,0])
def P(*a): print(*a); sys.stdout.flush()

be=libusb_package.get_libusb1_backend()
dev=usb.core.find(idVendor=VID,idProduct=PID,backend=be)
if dev is None: P("camera not found / another program has it open"); sys.exit(1)
usb.util.claim_interface(dev,1); dev.set_interface_altsetting(interface=1,alternate_setting=1)
dev.write(EP_OUT,MFI,timeout=500)
try: dev.read(EP_IN,64,timeout=300)
except usb.core.USBError: pass
dev.write(EP_OUT,C05,timeout=500)

P("\n>>> PRESS AND RELEASE THE HARDWARE BUTTON REPEATEDLY NOW (10 s) <<<\n")
bits = {0:0,1:0,2:0,3:0,4:0}
vals = {}
pkts = 0
end = time.time()+10
while time.time()<end:
    try: r=bytes(dev.read(EP_IN,0x4400,timeout=400))
    except usb.core.USBError: continue
    if len(r)>7 and r[0]==0xAA and r[1]==0xBB and r[2]==7:
        pkts += 1
        b7 = r[7]
        vals[b7] = vals.get(b7,0)+1
        for k in bits:
            if b7 & (1<<k): bits[k]+=1

dev.write(EP_OUT,C08,timeout=300)
usb.util.release_interface(dev,1); usb.util.dispose_resources(dev)

P(f"\nCID-7 packets seen: {pkts}")
P("distinct byte[7] values: " + ", ".join(f"0x{v:02X}(x{n})" for v,n in sorted(vals.items())))
names = {0:"hasg",1:"picbutton",2:"zoom",3:"zoomup",4:"zoomdown"}
for k in range(5):
    P(f"  bit{k} {names[k]:9}: set in {bits[k]} packets")
P("\n=> if 'picbutton' (bit1) count > 0, the button works and I can wire it in.")
