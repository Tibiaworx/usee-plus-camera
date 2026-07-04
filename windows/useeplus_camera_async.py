"""
High-throughput async driver for the Usee+Plus / supercamera (VID 2CE3 / PID 3828).

Uses libusb's asynchronous API (many in-flight bulk IN transfers) so the USB pipe
stays saturated instead of one-blocking-read-at-a-time. Also supports switching
camera / resolution on the fly.

Deps: libusb1 (import usb1), libusb-package, numpy, opencv-python.
WinUSB must be bound to Interface 1 (Zadig).
"""
import os
import threading
import queue
import libusb_package

# point usb1 at the bundled libusb-1.0.dll before importing it
os.add_dll_directory(os.path.dirname(libusb_package.get_library_path()))
import usb1  # noqa: E402
import numpy as np  # noqa: E402
import cv2  # noqa: E402

VID, PID = 0x2CE3, 0x3828
INTF, ALT = 1, 1
EP_OUT, EP_IN = 0x01, 0x81

CMD_MFI  = bytes([0xFF, 0x55, 0xFF, 0x55, 0xEE, 0x10])
CMD_OPEN = bytes([0xBB, 0xAA, 0x05, 0x00, 0x00])
CMD_PULL = bytes([0xBB, 0xAA, 0x06, 0x00, 0x00])
CMD_STOP = bytes([0xBB, 0xAA, 0x08, 0x00, 0x00])

PKT_HEADER = 12
READ_SIZE  = 0x4400
SOI, EOI   = b"\xff\xd8", b"\xff\xd9"
MAX_BUF    = 4 << 20   # 4 MB guard

# resolution bitmask value -> (w, h)
RES = {0x01: (320, 240), 0x02: (480, 480), 0x04: (640, 480), 0x08: (1280, 720),
       0x10: (1280, 960), 0x20: (1920, 1080), 0x40: (1920, 1440), 0x80: (2592, 1944)}


class UseePlusCameraAsync:
    def __init__(self, num_transfers=16, timeout_ms=2000):
        self.num_transfers = num_transfers
        self.timeout_ms = timeout_ms
        self.ctx = usb1.USBContext()
        self.handle = None
        self._buf = bytearray()
        self._q = queue.Queue(maxsize=4)   # raw JPEG bytes; small = low latency
        self._transfers = []
        self._running = False
        self._thread = None
        self._write_lock = threading.Lock()
        self._empty_timeouts = 0
        # Per-frame sidecar flags live in byte[7] of each CID-7 image packet
        # (confirmed via Ghidra decompile of libOtgCamera.so handle_pro/UCallBackHandle1):
        #   bit0=hasg  bit1=picbutton  bit2=zoom  bit3=zoomup  bit4=zoomdown
        self.button = False        # hardware shutter button, current state
        self.button_presses = 0    # monotonic count of button-press edges (app consumes this)
        self.zoom = self.zoomup = self.zoomdown = False
        self.has_gsensor = False   # true if any packet reports hasg
        self.angle = None          # g-sensor tilt (this unit has none -> stays None)
        self._prev_btn = False

    # -- lifecycle -------------------------------------------------------
    def open(self):
        self.ctx.open()
        self.handle = self.ctx.openByVendorIDAndProductID(
            VID, PID, skip_on_error=False)
        if self.handle is None:
            raise RuntimeError(f"{VID:04X}:{PID:04X} not found / WinUSB not bound")
        self.handle.claimInterface(INTF)
        self.handle.setInterfaceAltSetting(INTF, ALT)
        self._write(CMD_MFI)
        try:
            self.handle.bulkRead(EP_IN, 64, timeout=300)
        except usb1.USBError:
            pass
        self._write(CMD_OPEN)

        self._running = True
        for _ in range(self.num_transfers):
            t = self.handle.getTransfer()
            t.setBulk(EP_IN, READ_SIZE, callback=self._on_transfer,
                      timeout=self.timeout_ms)
            t.submit()
            self._transfers.append(t)
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()
        return self

    def close(self):
        self._running = False
        if self.handle is not None:
            try:
                self._write(CMD_STOP)
            except Exception:
                pass
        # let event loop drain / cancel
        for t in self._transfers:
            try:
                t.cancel()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=1.0)
        if self.handle is not None:
            try:
                self.handle.releaseInterface(INTF)
            except Exception:
                pass
            self.handle.close()
            self.handle = None
        try:
            self.ctx.close()
        except Exception:
            pass

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # -- io --------------------------------------------------------------
    def _write(self, data):
        with self._write_lock:
            return self.handle.bulkWrite(EP_OUT, data, timeout=800)

    def _event_loop(self):
        while self._running:
            try:
                self.ctx.handleEventsTimeout(0.1)
            except usb1.USBError:
                break

    def _on_transfer(self, transfer):
        st = transfer.getStatus()
        # consume any received bytes on BOTH completion and timeout: a bulk read
        # that times out mid-frame may still carry a full packet we must not drop.
        if st in (usb1.TRANSFER_COMPLETED, usb1.TRANSFER_TIMED_OUT):
            n = transfer.getActualLength()
            if n > PKT_HEADER:
                data = transfer.getBuffer()[:n]
                if data[0] == 0xAA and data[1] == 0xBB:
                    if data[2] in (7, 10):          # image packet: byte[7] = flags
                        self._flags(data[7])
                    self._buf += data[PKT_HEADER:]
                    self._carve()
            elif st == usb1.TRANSFER_TIMED_OUT:
                # genuinely idle -> gently nudge the device to resume streaming
                self._empty_timeouts += 1
                if self._empty_timeouts % 3 == 0:
                    try:
                        self._write(CMD_PULL)
                    except Exception:
                        pass
        # resubmit unless shutting down / cancelled
        if self._running and st != usb1.TRANSFER_CANCELLED:
            try:
                transfer.submit()
            except usb1.USBError:
                pass

    def _carve(self):
        buf = self._buf
        while True:
            s = buf.find(SOI)
            if s < 0:
                if len(buf) > MAX_BUF:
                    del buf[:-4]
                break
            if s > 0:
                del buf[:s]
            e = buf.find(EOI)
            if e < 0:
                if len(buf) > MAX_BUF:
                    del buf[:]
                break
            jpg = bytes(buf[:e + 2])
            del buf[:e + 2]
            # push newest, drop oldest if full (keep latency low)
            try:
                self._q.put_nowait(jpg)
            except queue.Full:
                try:
                    self._q.get_nowait()
                    self._q.put_nowait(jpg)
                except queue.Empty:
                    pass

    def _flags(self, b7):
        """Decode the byte[7] flags of an image packet (runs on the USB thread)."""
        self.has_gsensor = self.has_gsensor or bool(b7 & 0x01)
        btn = bool(b7 & 0x02)
        if btn and not self._prev_btn:      # rising edge = one press
            self.button_presses += 1
        self._prev_btn = btn
        self.button = btn
        self.zoom = bool(b7 & 0x04)
        self.zoomup = bool(b7 & 0x08)
        self.zoomdown = bool(b7 & 0x10)

    # -- public ----------------------------------------------------------
    def set_resolution(self, res_value, cam=1):
        """res_value: a key of RES (e.g. 0x08 for 1280x720). cam: camera index."""
        cmd = bytearray([0xBB, 0xAA, 0x0B, 0x00, 0x02, cam & 0xFF,
                         res_value & 0xFF, 0x00])
        self._write(bytes(cmd))

    def frames(self):
        """Yield decoded BGR frames."""
        while self._running or not self._q.empty():
            try:
                jpg = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                yield img
