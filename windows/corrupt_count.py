import time, sys
from useeplus_camera_async import UseePlusCameraAsync
# count frames whose JPEG fails to decode cleanly (compare vs stderr warnings)
import cv2, numpy as np
with UseePlusCameraAsync() as cam:
    n = 0; t = time.time()
    for f in cam.frames():
        n += 1
        if n >= 120:
            break
    dt = time.time() - t
    sys.stderr.flush()
    print(f"\n{n} good frames in {dt:.1f}s = {n/dt:.1f} fps, "
          f"corrupt_skipped={cam.corrupt_skipped} presses={cam.button_presses}", flush=True)
