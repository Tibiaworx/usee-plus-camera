"""Look for a metadata block BETWEEN frames (FF D9 .. next FF D8) in reads.pkl."""
import os, pickle
HERE = os.path.dirname(os.path.abspath(__file__))
reads = pickle.load(open(os.path.join(HERE, "reads.pkl"), "rb"))

# strip 12-byte per-packet header, concat to logical payload stream
buf = bytearray()
for r in reads:
    if len(r) > 12 and r[0] == 0xAA and r[1] == 0xBB:
        buf += r[12:]

# find frames and the gaps between them
i = 0
gaps = []
frames = []
while True:
    s = buf.find(b"\xff\xd8", i)
    if s < 0:
        break
    e = buf.find(b"\xff\xd9", s)
    if e < 0:
        break
    frames.append((s, e + 2))
    i = e + 2

print(f"{len(frames)} frames found")
for k in range(len(frames) - 1):
    end = frames[k][1]
    nxt = frames[k + 1][0]
    gap = bytes(buf[end:nxt])
    gaps.append(gap)
    if k < 6:
        print(f"  gap {k}: {len(gap)} bytes: {' '.join(f'{x:02X}' for x in gap[:40])}"
              + (" ..." if len(gap) > 40 else ""))

if gaps:
    lens = [len(g) for g in gaps]
    print(f"\ngap length: min={min(lens)} max={max(lens)} "
          f"(constant={len(set(lens))==1})")
