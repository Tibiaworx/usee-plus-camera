"""
Userspace Windows driver for the i4season "Usee+Plus / supercamera" USB camera.
VID 0x2CE3 / PID 0x3828, interface MI_01 ("com.useeplus.protocol"), via WinUSB+libusb.

Requires: pyusb, libusb-package, numpy, opencv-python  and the WinUSB driver bound
to Interface 1 (via Zadig).

Usage:
    from useeplus_camera import UseePlusCamera
    with UseePlusCamera() as cam:
        for frame in cam.frames():      # frame = BGR numpy array (H,W,3)
            ...
"""
import usb.core
import usb.util
import libusb_package
import numpy as np
import cv2

VID, PID = 0x2CE3, 0x3828
INTF, ALT = 1, 1
EP_OUT, EP_IN = 0x01, 0x81

CMD_MFI  = bytes([0xFF, 0x55, 0xFF, 0x55, 0xEE, 0x10])
CMD_OPEN = bytes([0xBB, 0xAA, 0x05, 0x00, 0x00])   # latch / start stream
CMD_PULL = bytes([0xBB, 0xAA, 0x06, 0x00, 0x00])   # nudge next chunk
CMD_STOP = bytes([0xBB, 0xAA, 0x08, 0x00, 0x00])

PKT_HEADER = 12          # 8-byte transport header + 4-byte rotating tag
READ_SIZE  = 0x4400      # max bytes per bulk read
SOI, EOI   = b"\xff\xd8", b"\xff\xd9"


class UseePlusCamera:
    def __init__(self, read_timeout=500):
        self.read_timeout = read_timeout
        self.dev = None
        self._buf = bytearray()
        self._stalls = 0

    # -- lifecycle -------------------------------------------------------
    def open(self):
        be = libusb_package.get_libusb1_backend()
        self.dev = usb.core.find(idVendor=VID, idProduct=PID, backend=be)
        if self.dev is None:
            raise RuntimeError(
                f"Camera {VID:04X}:{PID:04X} not found. Plugged in? "
                "WinUSB bound to Interface 1 via Zadig?")
        usb.util.claim_interface(self.dev, INTF)
        self.dev.set_interface_altsetting(interface=INTF, alternate_setting=ALT)
        self._handshake()
        return self

    def _handshake(self):
        self._write(CMD_MFI)
        self._read(64)               # ignored wake reply (may time out)
        self._write(CMD_OPEN)        # start streaming

    def close(self):
        if self.dev is not None:
            try:
                self._write(CMD_STOP)
            except usb.core.USBError:
                pass
            usb.util.release_interface(self.dev, INTF)
            usb.util.dispose_resources(self.dev)
            self.dev = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # -- low level -------------------------------------------------------
    def _write(self, data, timeout=800):
        return self.dev.write(EP_OUT, data, timeout=timeout)

    def _read(self, n=READ_SIZE):
        try:
            return bytes(self.dev.read(EP_IN, n, timeout=self.read_timeout))
        except usb.core.USBError:
            return b""

    # -- framing ---------------------------------------------------------
    def _pump(self):
        """Do one read; append stripped payload; poke on stall."""
        r = self._read()
        if r and len(r) > PKT_HEADER and r[0] == 0xAA and r[1] == 0xBB:
            self._buf += r[PKT_HEADER:]
            self._stalls = 0
        else:
            self._stalls += 1
            self._write(CMD_PULL if self._stalls % 2 else CMD_OPEN)

    def _carve(self):
        """Return one raw JPEG (bytes) if a full SOI..EOI is buffered, else None."""
        s = self._buf.find(SOI)
        if s < 0:
            if len(self._buf) > 4:            # drop junk, keep tail for split marker
                del self._buf[:-4]
            return None
        if s > 0:
            del self._buf[:s]                 # align to SOI
        e = self._buf.find(EOI)
        if e < 0:
            return None
        jpg = bytes(self._buf[:e + 2])
        del self._buf[:e + 2]
        return jpg

    def frames(self, max_stalls=40):
        """Yield decoded BGR frames forever (until device error / stop)."""
        consec_empty = 0
        while True:
            jpg = self._carve()
            if jpg is None:
                self._pump()
                consec_empty = self._stalls
                if consec_empty > max_stalls:
                    raise RuntimeError("stream stalled (no data). Re-plug camera?")
                continue
            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                yield img
