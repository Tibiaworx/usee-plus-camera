"""
Usee+Plus camera desktop app (Windows).

Features:
  - live 640x480 preview (async driver, ~8 fps, device-limited)
  - auto-reconnect: unplug/replug the camera and it re-acquires automatically
  - snapshot (key 's' or the camera's hardware button once wired)
  - record .avi (key 'r')
  - tilt auto-rotate (once g-sensor metadata is wired)

Keys:  q/Esc quit   s snapshot   r record   f flip/rotate lock   h hide HUD
"""
import os
import time
import datetime
import cv2

try:
    from useeplus_camera_async import UseePlusCameraAsync as Camera
except Exception as e:   # pragma: no cover
    raise SystemExit(f"driver import failed: {e}")

APP = "Usee+Plus Camera"
HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "captures")
os.makedirs(SHOTS, exist_ok=True)


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def draw_hud(img, fps, recording, angle, show):
    if not show:
        return img
    h, w = img.shape[:2]
    out = img.copy()
    parts = [f"{w}x{h}", f"{fps:4.1f} fps"]
    if angle is not None:
        parts.append(f"tilt {angle:+.0f}")
    if recording:
        parts.append("* REC")
    label = "   ".join(parts)
    cv2.rectangle(out, (0, 0), (w, 24), (0, 0, 0), -1)
    cv2.putText(out, label, (8, 17), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (0, 255, 0), 1, cv2.LINE_AA)
    cv2.putText(out, "q quit  s snap  r rec  h hud", (8, h - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1, cv2.LINE_AA)
    return out


def run_once():
    """One connected session. Returns 'quit' or 'reconnect'."""
    fps_t, fps_n, fps = time.time(), 0, 0.0
    writer = None
    recording = False
    show_hud = True

    with Camera() as cam:
        print("connected - streaming")
        prev_presses = cam.button_presses
        cv2.namedWindow(APP, cv2.WINDOW_NORMAL)
        for frame in cam.frames():
            fps_n += 1
            if time.time() - fps_t >= 0.5:
                fps = fps_n / (time.time() - fps_t)
                fps_t, fps_n = time.time(), 0

            # hardware shutter button -> snapshot on each new press
            btn_flash = False
            if cam.button_presses != prev_presses:
                prev_presses = cam.button_presses
                fn = os.path.join(SHOTS, f"btn_{stamp()}.png")
                cv2.imwrite(fn, frame)
                print("hardware-button snapshot:", fn)
                btn_flash = True

            # tilt auto-rotate (only if angle known)
            disp = frame
            if cam.angle is not None:
                a = cam.angle
                if -135 <= a < -45:
                    disp = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                elif 45 <= a < 135:
                    disp = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                elif a >= 135 or a < -135:
                    disp = cv2.rotate(frame, cv2.ROTATE_180)

            if recording and writer is not None:
                writer.write(frame)

            hud = draw_hud(disp, fps, recording, cam.angle, show_hud)
            if btn_flash:
                h, w = hud.shape[:2]
                cv2.rectangle(hud, (0, 0), (w - 1, h - 1), (255, 255, 255), 14)
                cv2.putText(hud, "SHUTTER", (w // 2 - 90, h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3, cv2.LINE_AA)
            cv2.imshow(APP, hud)

            k = cv2.waitKey(1) & 0xFF
            if k in (ord('q'), 27):
                if writer:
                    writer.release()
                return "quit"
            elif k == ord('s'):
                fn = os.path.join(SHOTS, f"snap_{stamp()}.png")
                cv2.imwrite(fn, frame)
                print("snapshot:", fn)
            elif k == ord('h'):
                show_hud = not show_hud
            elif k == ord('r'):
                recording = not recording
                if recording:
                    h, w = frame.shape[:2]
                    fn = os.path.join(SHOTS, f"rec_{stamp()}.avi")
                    writer = cv2.VideoWriter(fn, cv2.VideoWriter_fourcc(*"MJPG"),
                                             max(1.0, fps or 8.0), (w, h))
                    print("recording ->", fn)
                elif writer:
                    writer.release(); writer = None
                    print("recording stopped")

            if cv2.getWindowProperty(APP, cv2.WND_PROP_VISIBLE) < 1:
                if writer:
                    writer.release()
                return "quit"

    return "reconnect"


def main():
    print(f"{APP} - starting. Close the window or press q to quit.")
    while True:
        try:
            result = run_once()
        except Exception as e:
            # device not present / lost -> wait and retry
            print(f"camera unavailable ({e}); retrying in 1s...  "
                  "(plug in the camera / close other viewers)")
            _wait_screen()
            if _quit_pressed():
                break
            time.sleep(1.0)
            continue
        if result == "quit":
            break
    cv2.destroyAllWindows()
    print("bye")


def _wait_screen():
    import numpy as np
    img = np.zeros((240, 480, 3), np.uint8)
    cv2.putText(img, "Waiting for camera...", (40, 120),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2, cv2.LINE_AA)
    cv2.putText(img, "plug it in / close other viewers  (q to quit)", (30, 160),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1, cv2.LINE_AA)
    cv2.imshow(APP, img)


def _quit_pressed():
    k = cv2.waitKey(300) & 0xFF
    return k in (ord('q'), 27)


if __name__ == "__main__":
    main()
