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
          f"counter={cam.frame_counter} dropped_packets={cam.dropped}")
