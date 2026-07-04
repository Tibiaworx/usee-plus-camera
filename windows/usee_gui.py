"""
Usee+Plus Camera - Qt (PySide6) desktop GUI.

Live preview + thumbnail gallery + toolbar (snapshot / record / flip / rotate /
fullscreen), auto-reconnect, and hardware-shutter-button capture.

Run:  python usee_gui.py      (or the packaged UseePlusCameraGUI.exe)
"""
import os
import sys
import time
import datetime

import cv2
import numpy as np

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize
from PySide6.QtGui import QImage, QPixmap, QIcon, QAction, QPainter, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QListWidget, QListWidgetItem, QSplitter,
    QWidget, QVBoxLayout, QToolBar, QStatusBar, QStyle, QSizePolicy, QFrame
)

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "captures")
os.makedirs(SHOTS, exist_ok=True)


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


# --------------------------------------------------------------------------- #
# Camera thread: owns the USB driver, handles connect/stream/reconnect.
# --------------------------------------------------------------------------- #
class CameraThread(QThread):
    frameReady = Signal(object)      # BGR numpy frame
    connected = Signal(int, int)     # width, height
    disconnected = Signal()
    buttonPressed = Signal()

    def __init__(self):
        super().__init__()
        self._running = True

    def run(self):
        # import here so a driver/import error surfaces as "disconnected", not a crash
        try:
            from useeplus_camera_async import UseePlusCameraAsync
        except Exception:
            self.disconnected.emit()
            return
        while self._running:
            try:
                with UseePlusCameraAsync() as cam:
                    first = True
                    prev_presses = cam.button_presses
                    for frame in cam.frames():
                        if not self._running:
                            return
                        if first:
                            h, w = frame.shape[:2]
                            self.connected.emit(w, h)
                            first = False
                        if cam.button_presses != prev_presses:
                            prev_presses = cam.button_presses
                            self.buttonPressed.emit()
                        self.frameReady.emit(frame)
            except Exception:
                self.disconnected.emit()
                for _ in range(10):           # ~1s, but stay responsive to stop
                    if not self._running:
                        return
                    self.msleep(100)

    def stop(self):
        self._running = False


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Usee+Plus Camera")
        self.resize(940, 620)

        self.latest = None          # latest processed BGR frame (what you see = what you save)
        self.flip_h = False
        self.flip_v = False
        self.rotate = 0             # 0/90/180/270
        self.recording = False
        self.writer = None
        self.flash_until = 0.0
        self._fps_n = 0
        self._fps = 0.0
        self.capture_count = 0

        # --- central: video | gallery ---
        self.video = QLabel("Starting…")
        self.video.setAlignment(Qt.AlignCenter)
        self.video.setMinimumSize(480, 360)
        self.video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video.setStyleSheet("background:#111; color:#888;")

        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setIconSize(QSize(120, 90))
        self.gallery.setResizeMode(QListWidget.Adjust)
        self.gallery.setMovement(QListWidget.Static)
        self.gallery.setFixedWidth(160)
        self.gallery.setSpacing(6)
        self.gallery.itemDoubleClicked.connect(self._open_capture)
        self._load_existing_captures()

        split = QSplitter()
        split.addWidget(self.video)
        split.addWidget(self.gallery)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        self.setCentralWidget(split)

        self._build_toolbar()
        self._build_statusbar()

        # --- camera thread ---
        self.cam = CameraThread()
        self.cam.frameReady.connect(self._on_frame)
        self.cam.connected.connect(self._on_connected)
        self.cam.disconnected.connect(self._on_disconnected)
        self.cam.buttonPressed.connect(self._on_button)
        self.cam.start()

        # fps label refresh
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._refresh_fps)
        self._fps_timer.start(1000)

    # ---- UI construction ----
    def _icon(self, sp):
        return self.style().standardIcon(sp)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(Qt.BottomToolBarArea, tb)

        self.act_snap = QAction(self._icon(QStyle.SP_DialogSaveButton), "Snapshot", self)
        self.act_snap.setShortcut("S")
        self.act_snap.triggered.connect(lambda: self._snapshot("snap"))
        tb.addAction(self.act_snap)

        self.act_rec = QAction(self._icon(QStyle.SP_MediaPlay), "Record", self)
        self.act_rec.setCheckable(True)
        self.act_rec.setShortcut("R")
        self.act_rec.toggled.connect(self._toggle_record)
        tb.addAction(self.act_rec)

        tb.addSeparator()

        self.act_fliph = QAction("Flip ↔", self); self.act_fliph.setCheckable(True)
        self.act_fliph.toggled.connect(lambda v: setattr(self, "flip_h", v))
        tb.addAction(self.act_fliph)

        self.act_flipv = QAction("Flip ↕", self); self.act_flipv.setCheckable(True)
        self.act_flipv.toggled.connect(lambda v: setattr(self, "flip_v", v))
        tb.addAction(self.act_flipv)

        self.act_rot = QAction("Rotate ↻", self)
        self.act_rot.triggered.connect(self._cycle_rotate)
        tb.addAction(self.act_rot)

        tb.addSeparator()

        self.act_full = QAction(self._icon(QStyle.SP_TitleBarMaxButton), "Fullscreen", self)
        self.act_full.setShortcut("F11")
        self.act_full.triggered.connect(self._toggle_fullscreen)
        tb.addAction(self.act_full)

        self.act_folder = QAction(self._icon(QStyle.SP_DirOpenIcon), "Open captures", self)
        self.act_folder.triggered.connect(lambda: os.startfile(SHOTS))
        tb.addAction(self.act_folder)

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_conn = QLabel("  ● connecting…  ")
        self.lbl_conn.setStyleSheet("color:#e0a000;")
        self.lbl_res = QLabel("--")
        self.lbl_fps = QLabel("0.0 fps")
        self.lbl_count = QLabel("captures: 0")
        for w in (self.lbl_conn, self.lbl_res, self.lbl_fps, self.lbl_count):
            sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setFrameShadow(QFrame.Sunken)
            sb.addWidget(w); sb.addWidget(sep)

    # ---- camera signal slots ----
    def _on_connected(self, w, h):
        self.lbl_conn.setText("  ● live  ")
        self.lbl_conn.setStyleSheet("color:#28c840;")
        self.lbl_res.setText(f"{w}×{h}")

    def _on_disconnected(self):
        self.lbl_conn.setText("  ● waiting for camera…  ")
        self.lbl_conn.setStyleSheet("color:#e0504a;")
        self.video.setText("Waiting for camera…\n\nplug it in / close other viewers")

    def _on_button(self):
        self._snapshot("btn")
        self.flash_until = time.time() + 0.18

    def _on_frame(self, frame):
        frame = self._process(frame)
        self.latest = frame
        self._fps_n += 1
        if self.recording and self.writer is not None:
            self.writer.write(frame)
        self._show(frame)

    # ---- image pipeline ----
    def _process(self, frame):
        if self.flip_h:
            frame = cv2.flip(frame, 1)
        if self.flip_v:
            frame = cv2.flip(frame, 0)
        if self.rotate == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotate == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif self.rotate == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    def _show(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg).scaled(
            self.video.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if time.time() < self.flash_until:
            p = QPainter(pix)
            p.setPen(QColor(255, 255, 255))
            for i in range(8):
                p.drawRect(i, i, pix.width() - 1 - 2 * i, pix.height() - 1 - 2 * i)
            p.end()
        self.video.setPixmap(pix)

    # ---- actions ----
    def _snapshot(self, prefix):
        if self.latest is None:
            return
        fn = os.path.join(SHOTS, f"{prefix}_{stamp()}.png")
        cv2.imwrite(fn, self.latest)
        self._add_thumb(fn)
        self.capture_count += 1
        self.lbl_count.setText(f"captures: {self.capture_count}")

    def _toggle_record(self, on):
        if on:
            if self.latest is None:
                self.act_rec.setChecked(False); return
            h, w = self.latest.shape[:2]
            fn = os.path.join(SHOTS, f"rec_{stamp()}.avi")
            self.writer = cv2.VideoWriter(fn, cv2.VideoWriter_fourcc(*"MJPG"),
                                          max(1.0, self._fps or 8.0), (w, h))
            self.recording = True
            self.act_rec.setIcon(self._icon(QStyle.SP_MediaStop))
            self.act_rec.setText("Stop")
        else:
            self.recording = False
            if self.writer:
                self.writer.release(); self.writer = None
            self.act_rec.setIcon(self._icon(QStyle.SP_MediaPlay))
            self.act_rec.setText("Record")

    def _cycle_rotate(self):
        self.rotate = (self.rotate + 90) % 360
        self.act_rot.setText(f"Rotate ↻ {self.rotate}°")

    def _toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    # ---- gallery ----
    def _add_thumb(self, path):
        item = QListWidgetItem(QIcon(path), os.path.basename(path))
        item.setData(Qt.UserRole, path)
        self.gallery.insertItem(0, item)

    def _load_existing_captures(self):
        files = sorted((f for f in os.listdir(SHOTS) if f.lower().endswith(".png")),
                       reverse=True)[:40]
        for f in files:
            self._add_thumb(os.path.join(SHOTS, f))

    def _open_capture(self, item):
        path = item.data(Qt.UserRole)
        if path and os.path.exists(path):
            os.startfile(path)

    # ---- misc ----
    def _refresh_fps(self):
        self._fps = self._fps_n
        self._fps_n = 0
        self.lbl_fps.setText(f"{self._fps:.0f} fps")

    def resizeEvent(self, e):
        if self.latest is not None:
            self._show(self.latest)
        super().resizeEvent(e)

    def closeEvent(self, e):
        self.cam.stop()
        self.cam.wait(1500)
        if self.writer:
            self.writer.release()
        super().closeEvent(e)


def _apply_dark(app):
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.Window, QColor(37, 37, 40))
    p.setColor(QPalette.WindowText, QColor(220, 220, 220))
    p.setColor(QPalette.Base, QColor(28, 28, 30))
    p.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
    p.setColor(QPalette.Text, QColor(220, 220, 220))
    p.setColor(QPalette.Button, QColor(50, 50, 54))
    p.setColor(QPalette.ButtonText, QColor(230, 230, 230))
    p.setColor(QPalette.Highlight, QColor(38, 120, 200))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(p)


def main():
    app = QApplication(sys.argv)
    _apply_dark(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
