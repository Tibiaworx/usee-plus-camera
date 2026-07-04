import time
from useeplus_camera_async import UseePlusCameraAsync

with UseePlusCameraAsync() as cam:
    n = 0; t = time.time()
    for f in cam.frames():
        n += 1
        if n >= 40:
            break
    dt = time.time() - t
    print(f"{n} frames in {dt:.1f}s = {n/dt:.1f} fps | "
          f"button_presses={cam.button_presses} has_gsensor={cam.has_gsensor} "
          f"zoom={cam.zoom}/{cam.zoomup}/{cam.zoomdown}")
