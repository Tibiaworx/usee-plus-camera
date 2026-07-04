import time
from useeplus_camera_async import UseePlusCameraAsync, RES

def measure(cam, secs=3.0):
    """Consume frames for `secs`, return (count, last_shape)."""
    n = 0; shape = None; t = time.time()
    for f in cam.frames():
        n += 1; shape = f.shape
        if time.time() - t >= secs:
            break
    return n / (time.time() - t), shape

with UseePlusCameraAsync(num_transfers=32) as cam:
    time.sleep(0.5)
    fps, shape = measure(cam, 3.0)
    print(f"default            : {shape} @ {fps:.1f} fps")

    for val in (0x01, 0x02, 0x04, 0x08, 0x10, 0x20):
        w, h = RES[val]
        cam.set_resolution(val, cam=1)
        time.sleep(1.2)                      # let it switch + flush old frames
        fps, shape = measure(cam, 3.0)
        got = f"{shape[1]}x{shape[0]}" if shape else "none"
        ok = "OK" if (shape and (shape[1], shape[0]) == (w, h)) else "??"
        print(f"set 0x{val:02X} ({w}x{h}) -> got {got:9} @ {fps:4.1f} fps  {ok}")
