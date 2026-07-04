import time
from useeplus_camera import UseePlusCamera

n = 0
t = time.time()
with UseePlusCamera() as cam:
    for f in cam.frames():
        n += 1
        if n == 1:
            print("first frame:", f.shape, f.dtype)
        if n >= 20:
            break
dt = time.time() - t
print(f"grabbed {n} frames in {dt:.1f}s = {n/dt:.1f} fps")
