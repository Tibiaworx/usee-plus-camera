import time
from useeplus_camera_async import UseePlusCameraAsync

N = 60
with UseePlusCameraAsync(num_transfers=32) as cam:
    t = time.time()
    n = 0
    first = None
    for f in cam.frames():
        n += 1
        if first is None:
            first = f.shape
            t = time.time()          # start timing after first frame (warmup)
            continue
        if n >= N:
            break
    dt = time.time() - t
    print(f"shape={first}  {n-1} frames in {dt:.2f}s = {(n-1)/dt:.1f} fps")
