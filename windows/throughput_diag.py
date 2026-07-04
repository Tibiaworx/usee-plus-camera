"""
Raw throughput + timing diagnostic (no JPEG decode). Answers:
 - packets/s and MB/s ceiling (are we transfer-bound or device-bound?)
 - inter-frame gap timing (steady stream vs bursty = exposure/sensor limited)
"""
import os, sys, time
import libusb_package
os.add_dll_directory(os.path.dirname(libusb_package.get_library_path()))
import usb1

VID, PID = 0x2CE3, 0x3828
EP_OUT, EP_IN = 0x01, 0x81
MFI=bytes([0xFF,0x55,0xFF,0x55,0xEE,0x10]); C05=bytes([0xBB,0xAA,0x05,0,0]); C08=bytes([0xBB,0xAA,0x08,0,0])
def P(*a): print(*a); sys.stdout.flush()

for NUM in (16, 64):
    ctx=usb1.USBContext(); ctx.open()
    h=ctx.openByVendorIDAndProductID(VID,PID,skip_on_error=False)
    h.claimInterface(1); h.setInterfaceAltSetting(1,1)
    h.bulkWrite(EP_OUT,MFI,timeout=500)
    try: h.bulkRead(EP_IN,64,timeout=300)
    except usb1.USBError: pass
    h.bulkWrite(EP_OUT,C05,timeout=500)

    stats={"pkts":0,"bytes":0,"frames":0,"partial":bytearray(),"frame_times":[]}
    running=[True]
    t0=[None]
    def cb(tr):
        st=tr.getStatus()
        if st==usb1.TRANSFER_COMPLETED:
            n=tr.getActualLength(); d=tr.getBuffer()[:n]
            if n>12 and d[0]==0xAA and d[1]==0xBB:
                if t0[0] is None: t0[0]=time.time()
                stats["pkts"]+=1; stats["bytes"]+=n
                pl=d[12:]; stats["partial"]+=pl
                # count frames by EOI
                while True:
                    e=stats["partial"].find(b"\xff\xd9")
                    if e<0: break
                    stats["frames"]+=1; stats["frame_times"].append(time.time())
                    del stats["partial"][:e+2]
                    if len(stats["partial"])>1_000_000: del stats["partial"][:]
        if running[0] and st!=usb1.TRANSFER_CANCELLED:
            try: tr.submit()
            except usb1.USBError: pass

    trs=[]
    for _ in range(NUM):
        tr=h.getTransfer(); tr.setBulk(EP_IN,0x4400,callback=cb,timeout=1000); tr.submit(); trs.append(tr)

    DUR=5.0; end=time.time()+DUR+1.0
    while time.time()<end and t0[0] is None:
        ctx.handleEventsTimeout(0.05)
    start=time.time()
    while time.time()-start<DUR:
        ctx.handleEventsTimeout(0.05)
    running[0]=False
    for tr in trs:
        try: tr.cancel()
        except: pass
    for _ in range(20): ctx.handleEventsTimeout(0.02)
    try: h.bulkWrite(EP_OUT,C08,timeout=300)
    except: pass
    h.releaseInterface(1); h.close(); ctx.close()

    dt=DUR
    ft=stats["frame_times"]
    gaps=[ (ft[i+1]-ft[i])*1000 for i in range(len(ft)-1) ] if len(ft)>1 else []
    P(f"\n== NUM_TRANSFERS={NUM} ==")
    P(f"  packets/s = {stats['pkts']/dt:.0f}   throughput = {stats['bytes']/dt/1e6:.2f} MB/s")
    P(f"  frames    = {stats['frames']}  ({stats['frames']/dt:.1f} fps)")
    if gaps:
        gaps.sort()
        P(f"  inter-frame gap ms: min={gaps[0]:.0f} median={gaps[len(gaps)//2]:.0f} max={gaps[-1]:.0f}")
        P(f"  packets/frame ~ {stats['pkts']/max(1,stats['frames']):.1f}")
