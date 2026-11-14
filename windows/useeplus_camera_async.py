"""
High-throughput async driver for the Usee+Plus / supercamera (VID 2CE3 / PID 3828).

Uses libusb's asynchronous API (many in-flight bulk IN transfers) so the USB pipe
stays saturated instead of one-blocking-read-at-a-time. Also supports switching
camera / resolution on the fly.

Deps: libusb1 (import usb1), libusb-package, numpy, opencv-python.
Supports the Interface 1 JPEG and Interface 0 raw YUYV layouts via WinUSB.
"""
import os
import io
import time
import threading
import queue
import libusb_package

# point usb1 at the bundled libusb-1.0.dll before importing it
os.add_dll_directory(os.path.dirname(libusb_package.get_library_path()))
import usb1  # noqa: E402
import numpy as np  # noqa: E402
import cv2  # noqa: E402
from PIL import Image  # noqa: E402  (used to validate JPEG completeness)

VID, PID = 0x2CE3, 0x3828
INTF, ALT = 1, 1
EP_OUT, EP_IN = 0x01, 0x81

RAW_WIDTH, RAW_HEIGHT = 640, 480
RAW_FRAME_BYTES = RAW_WIDTH * RAW_HEIGHT * 2
RAW_EP_OUT, RAW_EP_IN = 0x02, 0x82

CMD_MFI  = bytes([0xFF, 0x55, 0xFF, 0x55, 0xEE, 0x10])
CMD_OPEN = bytes([0xBB, 0xAA, 0x05, 0x00, 0x00])
CMD_PULL = bytes([0xBB, 0xAA, 0x06, 0x00, 0x00])
CMD_STOP = bytes([0xBB, 0xAA, 0x08, 0x00, 0x00])

PKT_HEADER = 12
READ_SIZE  = 0x4400
SOI, EOI   = b"\xff\xd8", b"\xff\xd9"
MAX_BUF    = 4 << 20   # 4 MB guard
# Device is self-paced at ~90 ms/frame (11 fps) - measured on the wire with a
# USB sniffer against the reference implementation. Anything past ~3 s of dead
# air means the link died, not that the scene is dark.
STALL_TIMEOUT = 3.0

# resolution bitmask value -> (w, h)
RES = {0x01: (320, 240), 0x02: (480, 480), 0x04: (640, 480), 0x08: (1280, 720),
       0x10: (1280, 960), 0x20: (1920, 1080), 0x40: (1920, 1440), 0x80: (2592, 1944)}


class UseePlusCameraAsync:
    def __init__(self, num_transfers=16, timeout_ms=2000):
        self.num_transfers = num_transfers
        self.timeout_ms = timeout_ms
        self.ctx = usb1.USBContext()
        self.handle = None
        self._interface = None
        self._raw_yuyv = False
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
        self.corrupt_skipped = 0   # truncated frames dropped before display
        self._prev_btn = False
        self.stalls = 0            # times the watchdog had to reopen the device
        self.torn_frames = 0       # frames discarded by the SOI-before-EOI guard
        self._usb_errors = 0       # transient USBErrors survived by the event loop
        self._last_frame_ts = 0.0
        self._wd_thread = None

    # -- lifecycle -------------------------------------------------------
    def open(self):
        try:
            self.ctx.open()
            self.handle = self.ctx.openByVendorIDAndProductID(
                VID, PID, skip_on_error=False)
            if self.handle is None:
                raise RuntimeError(f"{VID:04X}:{PID:04X} not found / WinUSB not bound")

            self._raw_yuyv = any(
                setting.getNumber() == 0
                and setting.getAlternateSetting() == 0
                and {RAW_EP_OUT, RAW_EP_IN}.issubset(
                    ep.getAddress() for ep in setting.iterEndpoints()
                    if (ep.getAttributes() & 0x03) == 2
                )
                for setting in self.handle.getDevice().iterSettings()
            )
            interface = 0 if self._raw_yuyv else INTF
            self.handle.claimInterface(interface)
            self._interface = interface
            if self._raw_yuyv:
                self.handle.controlRead(0xA0, 0, 5, 0, 512, timeout=2000)
                sent = self.handle.controlWrite(
                    0x20, 1, 5, 0, b"0" * 64, timeout=2000
                )
                if sent != 64:
                    raise RuntimeError("Incomplete YUYV start request")
                self._running = True
            else:
                self.handle.setInterfaceAltSetting(INTF, ALT)
                self._start_jpeg()
        except Exception:
            self.close()
            raise
        return self

    def _start_jpeg(self):
        self._write(CMD_MFI)
        try:
            self.handle.bulkRead(EP_IN, 64, timeout=300)
        except usb1.USBError:
            pass
        self._write(CMD_OPEN)

        self._running = True
        self._last_frame_ts = time.time()
        for _ in range(self.num_transfers):
            t = self.handle.getTransfer()
            t.setBulk(EP_IN, READ_SIZE, callback=self._on_transfer,
                      timeout=self.timeout_ms)
            t.submit()
            self._transfers.append(t)
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()
        self._wd_thread = threading.Thread(target=self._watchdog, daemon=True)
        self._wd_thread.start()

    def close(self):
        self._running = False
        if self._interface is not None and self.handle is not None and not self._raw_yuyv:
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
        if self._wd_thread:
            self._wd_thread.join(timeout=1.5)
        if self.handle is not None:
            if self._interface is not None:
                try:
                    self.handle.releaseInterface(self._interface)
                except usb1.USBError:
                    pass
            self.handle.close()
            self.handle = None
        self._interface = None
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
        # NOTE: a transient USBError (bus reset, timeout race, device NAK storm)
        # must NOT kill this loop. Breaking here orphans every in-flight transfer
        # and the stream dies permanently with no signal to the caller - the app
        # keeps painting its last frame and looks alive. Confirmed with a USB
        # sniffer: after the break the host stops emitting IN tokens entirely
        # (zero packets on the wire) until the process is restarted.
        while self._running:
            try:
                self.ctx.handleEventsTimeout(0.1)
            except usb1.USBError:
                self._usb_errors += 1
                continue

    def _watchdog(self):
        """Reopen the device if no frame has arrived for STALL_TIMEOUT seconds."""
        while self._running:
            time.sleep(1.0)
            if not self._running:
                break
            idle = time.time() - self._last_frame_ts
            if idle < STALL_TIMEOUT:
                continue
            self.stalls += 1
            try:
                self._reopen()
            except Exception:
                pass
            self._last_frame_ts = time.time()   # don't thrash if reopen failed

    def _reopen(self):
        """Tear the USB session down and bring it back up, in place."""
        for t in self._transfers:
            try:
                t.cancel()
            except Exception:
                pass
        self._transfers = []
        if self.handle is not None:
            try:
                self.handle.releaseInterface(INTF)
            except Exception:
                pass
            try:
                self.handle.close()
            except Exception:
                pass
            self.handle = None
        time.sleep(0.2)
        self.handle = self.ctx.openByVendorIDAndProductID(
            VID, PID, skip_on_error=False)
        if self.handle is None:
            raise RuntimeError("device vanished during reopen")
        self.handle.claimInterface(INTF)
        self.handle.setInterfaceAltSetting(INTF, ALT)
        self._buf.clear()               # stale half-frame must not survive
        self._write(CMD_MFI)
        try:
            self.handle.bulkRead(EP_IN, 64, timeout=300)
        except usb1.USBError:
            pass
        self._write(CMD_OPEN)
        for _ in range(self.num_transfers):
            t = self.handle.getTransfer()
            t.setBulk(EP_IN, READ_SIZE, callback=self._on_transfer,
                      timeout=self.timeout_ms)
            t.submit()
            self._transfers.append(t)

    def _on_transfer(self, transfer):
        st = transfer.getStatus()
        # consume any received bytes on BOTH completion and timeout: a bulk read
        # that times out mid-frame may still carry a full packet we must not drop.
        if st in (usb1.TRANSFER_COMPLETED, usb1.TRANSFER_TIMED_OUT):
            n = transfer.getActualLength()
            if n > PKT_HEADER:
                data = transfer.getBuffer()[:n]
                # ONLY image packets (CID 7/10) carry JPEG data. Control replies
                # (CID 5 devinfo, 6 open-stream, 0x0B switch) must NOT be spliced
                # into the frame buffer - doing so truncates/corrupts the JPEG.
                if data[0] == 0xAA and data[1] == 0xBB and data[2] in (7, 10):
                    self._flags(data[7])
                    self._buf += data[PKT_HEADER:]
                    self._carve()
            elif st == usb1.TRANSFER_TIMED_OUT:
                # Just count it. Do NOT poke the device with CMD_PULL.
                #
                # The device auto-streams after CMD_OPEN - verified on the wire:
                # the reference implementation sends ZERO host->device packets
                # for the entire steady-state session. Worse, sending BB AA 06
                # while streaming actively KILLS the stream. Measured, with the
                # pull-vs-no-pull order reversed to rule out ordering effects:
                #     06 every 0.5s -> 2 frames  |  no pulls -> 86 frames
                #     06 every 0.5s -> 1 frame   |  no pulls -> 85 frames
                # The old "nudge on timeout" was therefore a death spiral: a
                # stall caused timeouts -> timeouts sent CMD_PULL -> the pull
                # killed the stream -> more timeouts -> more pulls. Recovery is
                # the watchdog's job (reopen), not a mid-stream poke.
                self._empty_timeouts += 1
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
            e = buf.find(EOI, 2)
            # A second SOI before the EOI means frame N lost packets mid-flight
            # and never terminated. Without this guard find(EOI) returns frame
            # N+1's terminator, both frames get spliced into one blob, and the
            # decode fails - so ONE dropped packet costs TWO frames. Drop only
            # the truncated frame and resync on the next SOI.
            s2 = buf.find(SOI, 2)
            if s2 >= 0 and (e < 0 or s2 < e):
                del buf[:s2]
                self.torn_frames += 1
                continue
            if e < 0:
                if len(buf) > MAX_BUF:
                    del buf[:]
                break
            jpg = bytes(buf[:e + 2])
            del buf[:e + 2]
            self._last_frame_ts = time.time()   # feed the stall watchdog
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
        if self._raw_yuyv:
            raise NotImplementedError("YUYV mode uses a fixed 640×480 stream")
        cmd = bytearray([0xBB, 0xAA, 0x0B, 0x00, 0x02, cam & 0xFF,
                         res_value & 0xFF, 0x00])
        self._write(bytes(cmd))

    def frames(self, skip_corrupt=True):
        """Yield decoded BGR frames. Truncated frames (dropped USB packets during a
        device stall) are skipped so the viewer holds the last good frame instead of
        flashing a partial image."""
        if self._raw_yuyv:
            yield from self._raw_frames()
            return

        while self._running or not self._q.empty():
            try:
                jpg = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if skip_corrupt:
                try:
                    Image.open(io.BytesIO(jpg)).load()   # raises on truncation
                except Exception:
                    self.corrupt_skipped += 1
                    continue
            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                yield img

    def _raw_frames(self):
        deadline = time.monotonic() + self.timeout_ms / 1000
        while self._running:
            data = self.handle.bulkRead(
                RAW_EP_IN, RAW_FRAME_BYTES, timeout=self.timeout_ms
            )
            if len(data) == RAW_FRAME_BYTES:
                pixels = np.frombuffer(data, dtype=np.uint8)
                pixels = pixels.reshape(RAW_HEIGHT, RAW_WIDTH, 2)
                yield cv2.cvtColor(pixels, cv2.COLOR_YUV2BGR_YUY2)
                deadline = time.monotonic() + self.timeout_ms / 1000
            elif time.monotonic() >= deadline:
                raise RuntimeError("No complete YUYV frame received")
