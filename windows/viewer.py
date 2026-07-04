"""
Live viewer for the Usee+Plus / supercamera on Windows.

  python viewer.py

Keys in the window:  q = quit,  s = save snapshot,  r = toggle recording (.avi)
"""
import os
import time
import cv2
from useeplus_camera_async import UseePlusCameraAsync as UseePlusCamera

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = "Usee+Plus camera (q=quit  s=snapshot  r=record)"


def main():
    fps_t, fps_n, fps = time.time(), 0, 0.0
    writer = None
    recording = False

    print("Opening camera...")
    with UseePlusCamera() as cam:
        print("Streaming. Focus the window and press q to quit.")
        cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
        for frame in cam.frames():
            # fps counter
            fps_n += 1
            if time.time() - fps_t >= 1.0:
                fps = fps_n / (time.time() - fps_t)
                fps_t, fps_n = time.time(), 0

            h, w = frame.shape[:2]
            hud = frame.copy()
            label = f"{w}x{h}  {fps:.1f} fps" + ("  * REC" if recording else "")
            cv2.putText(hud, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, (0, 255, 0), 1, cv2.LINE_AA)
            cv2.imshow(WIN, hud)

            if recording and writer is not None:
                writer.write(frame)

            k = cv2.waitKey(1) & 0xFF
            if k == ord('q'):
                break
            elif k == ord('s'):
                fn = os.path.join(HERE, f"snap_{int(time.time())}.png")
                cv2.imwrite(fn, frame)
                print("saved", fn)
            elif k == ord('r'):
                recording = not recording
                if recording:
                    fn = os.path.join(HERE, f"rec_{int(time.time())}.avi")
                    writer = cv2.VideoWriter(
                        fn, cv2.VideoWriter_fourcc(*"MJPG"),
                        max(1.0, fps or 5.0), (w, h))
                    print("recording ->", fn)
                else:
                    if writer:
                        writer.release(); writer = None
                    print("recording stopped")

            # exit if window closed
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:
                break

    if writer:
        writer.release()
    cv2.destroyAllWindows()
    print("done")


if __name__ == "__main__":
    main()
