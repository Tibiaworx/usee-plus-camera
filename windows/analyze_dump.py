"""Parse dump_raw.bin: map AA BB packets, JPEG markers, and header fields."""
import os, struct
HERE = os.path.dirname(os.path.abspath(__file__))
raw = open(os.path.join(HERE, "dump_raw.bin"), "rb").read()
print(f"total {len(raw)} bytes\n")

# find every AA BB packet header
i, pkts = 0, []
while True:
    j = raw.find(b"\xAA\xBB", i)
    if j < 0: break
    pkts.append(j); i = j + 2
print(f"AA BB headers at: {pkts}\n")

for idx, off in enumerate(pkts):
    end = pkts[idx + 1] if idx + 1 < len(pkts) else len(raw)
    seg = raw[off:end]
    h = seg[:16]
    b2 = seg[2] if len(seg) > 2 else None
    len16 = struct.unpack_from("<H", seg, 3)[0] if len(seg) >= 5 else None
    len32 = struct.unpack_from("<I", seg, 3)[0] if len(seg) >= 7 else None
    soi = seg.find(b"\xff\xd8")
    eoi = seg.find(b"\xff\xd9")
    print(f"pkt#{idx} off={off} seglen={len(seg)} b2=0x{b2:02X} "
          f"len16@3={len16}(0x{len16:04X}) len32@3={len32} "
          f"SOI@{soi} EOI@{eoi}")
    print(f"   head: {' '.join(f'{x:02X}' for x in h)}")

# global JPEG markers
def find_all(b, pat):
    out, i = [], 0
    while True:
        j = b.find(pat, i)
        if j < 0: break
        out.append(j); i = j + 1
    return out
print("SOI offsets:", find_all(raw, b"\xff\xd8"))
print("EOI offsets:", find_all(raw, b"\xff\xd9"))
