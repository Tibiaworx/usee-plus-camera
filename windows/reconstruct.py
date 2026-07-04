"""Offline: rebuild JPEGs from reads.pkl trying strip sizes; validate with PIL."""
import os, pickle, io
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
reads = pickle.load(open(os.path.join(HERE, "reads.pkl"), "rb"))

def decodes(f):
    try:
        im = Image.open(io.BytesIO(f)); im.load(); return im
    except Exception:
        return None

def rebuild(strip):
    buf = bytearray()
    for r in reads:
        if len(r) >= strip and r[0] == 0xAA and r[1] == 0xBB:
            buf += r[strip:]
    # carve frames
    frames, i = [], 0
    while True:
        s = buf.find(b"\xff\xd8", i)
        if s < 0: break
        e = buf.find(b"\xff\xd9", s)
        if e < 0: break
        frames.append(bytes(buf[s:e+2])); i = e + 2
    return frames

for strip in (8, 10, 11, 12, 13, 16):
    frames = rebuild(strip)
    ok = 0; info = ""; good = None
    for f in frames:
        im = decodes(f)
        if im:
            ok += 1
            if not info: info = f"{im.size} {im.mode}"; good = f
    print(f"strip={strip:2d}: {len(frames)} frames carved, {ok} decode OK  {info}")
    if good:
        open(os.path.join(HERE, f"good_strip{strip}.jpg"), "wb").write(good)
