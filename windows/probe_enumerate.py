"""
Usee+Plus camera (VID 2CE3 / PID 3828) - Step 1: enumerate & confirm raw access.
Read-only. Does NOT write to the device. Just dumps descriptors so we know the
real bulk endpoint addresses on interface MI_01 ("com.useeplus.protocol").

Run:  python probe_enumerate.py
"""
import sys
import usb.core
import usb.util
import libusb_package

VID, PID = 0x2CE3, 0x3828
TARGET_INTERFACE = 1  # MI_01 = com.useeplus.protocol  (MI_00 = iAP, ignore)

CLASS_NAMES = {0x00: "per-interface", 0x08: "Mass Storage", 0x0A: "CDC-Data",
               0xEF: "Misc/IAD", 0xFF: "Vendor-specific"}


def ep_type(ep):
    return {0: "CONTROL", 1: "ISO", 2: "BULK", 3: "INTERRUPT"}[
        usb.util.endpoint_type(ep.bmAttributes)]


def ep_dir(ep):
    return "IN" if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN else "OUT"


def main():
    be = libusb_package.get_libusb1_backend()
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=be)
    if dev is None:
        print(f"!! Device {VID:04X}:{PID:04X} NOT found. Is it plugged in?")
        sys.exit(1)

    print(f"== Found device {VID:04X}:{PID:04X} ==")
    for fld, name in (("bcdUSB", "USB ver"), ("bDeviceClass", "dev class"),
                      ("bDeviceSubClass", "subclass"), ("bDeviceProtocol", "protocol"),
                      ("bMaxPacketSize0", "ep0 maxpkt"), ("bcdDevice", "device ver")):
        print(f"   {name:12}: {getattr(dev, fld)}")
    for fld, name in (("iManufacturer", "Manufacturer"), ("iProduct", "Product"),
                      ("iSerialNumber", "Serial")):
        try:
            s = usb.util.get_string(dev, getattr(dev, fld))
        except Exception as e:
            s = f"<unreadable: {e}>"
        print(f"   {name:12}: {s!r}")

    found = {}
    for cfg in dev:
        print(f"\n-- Configuration {cfg.bConfigurationValue} "
              f"({cfg.bNumInterfaces} interfaces) --")
        for intf in cfg:
            cls = intf.bInterfaceClass
            cname = CLASS_NAMES.get(cls, f"0x{cls:02X}")
            try:
                iname = usb.util.get_string(dev, intf.iInterface)
            except Exception:
                iname = None
            print(f"  Interface {intf.bInterfaceNumber} alt {intf.bAlternateSetting}: "
                  f"class={cname} sub={intf.bInterfaceSubClass} proto={intf.bInterfaceProtocol} "
                  f"name={iname!r}")
            for ep in intf:
                print(f"      EP 0x{ep.bEndpointAddress:02X}  {ep_type(ep):9} "
                      f"{ep_dir(ep):3}  maxpkt={ep.wMaxPacketSize}")
                if intf.bInterfaceNumber == TARGET_INTERFACE and ep_type(ep) == "BULK":
                    found[ep_dir(ep)] = ep.bEndpointAddress

    print("\n== Result for MI_01 (interface 1) ==")
    if "IN" in found and "OUT" in found:
        print(f"   BULK OUT (host->device) = 0x{found['OUT']:02X}")
        print(f"   BULK IN  (device->host) = 0x{found['IN']:02X}")
        print("   -> Raw access CONFIRMED. Give these two numbers to Claude.")
    else:
        print(f"   Could not find both bulk endpoints on MI_01. Got: "
              f"{{k: hex(v) for k, v in found.items()}}")
        print("   (If interface 1 shows no endpoints, WinUSB may be bound to the "
              "wrong interface - re-check Zadig targeted 'Interface 1'.)")


if __name__ == "__main__":
    main()
