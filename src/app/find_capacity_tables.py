from pathlib import Path
import struct
import itertools

DAT_PATH = "../SCOT-94.DAT"
TEAM_COUNT = 64

# Provide your known ground truth here:
KNOWN = {
    # team_index: stadium_capacity_from_UI
    38: 86000,  # AC Milan
    36: 83000,  # Lazio
    15: 44000,  # Kaiserslautern
    # add more once you dump indices for them:
    # hearts_index: 17000,
    # dundee_index: 16000,
    # falkirk_index: 14000,
    # feyenoord_index: 64000,
    # rotor_index: 40000,
}

data = Path(DAT_PATH).read_bytes()
N = TEAM_COUNT

def table_byte(off: int):
    return data[off:off+N] if off+N <= len(data) else None

def table_u16(off: int):
    if off + 2*N > len(data): return None
    return list(struct.unpack_from("<" + "H"*N, data, off))

def table_u32(off: int):
    if off + 4*N > len(data): return None
    return list(struct.unpack_from("<" + "I"*N, data, off))

def score(pred):
    # mean absolute error over known points
    err = 0
    for idx, cap in KNOWN.items():
        err += abs(pred[idx] - cap)
    return err / max(1, len(KNOWN))

best = []

# 1) Try pairs of byte tables as low/high: cap = lo + 256*hi
# Scan a reasonable region first (you can widen later)
for lo_off in range(0, len(data)-N, 1):
    lo = table_byte(lo_off)
    if lo is None: break
    # quick filter: does lo have enough variation?
    if len(set(lo)) < 8:
        continue

    for hi_off in range(max(0, lo_off-2048), min(len(data)-N, lo_off+2048), 1):
        hi = table_byte(hi_off)
        if hi is None: continue
        if len(set(hi)) < 4:
            continue

        pred = [lo[i] + 256*hi[i] for i in range(N)]
        s = score(pred)
        if s < 500:  # threshold; tighten once you add more KNOWN points
            best.append(("byte_lo_hi", lo_off, hi_off, s))

# 2) Try uint16 tables with common scale factors
scales = [1, 5, 10, 20, 25, 50, 100]
for off in range(0, len(data)-2*N, 1):
    t = table_u16(off)
    if t is None: break
    # filter
    if max(t) < 200:  # too small
        continue
    for k in scales:
        pred = [v * k for v in t]
        s = score(pred)
        if s < 500:
            best.append((f"u16_x{k}", off, None, s))

# 3) Try uint32 tables directly (rare but possible)
for off in range(0, len(data)-4*N, 1):
    t = table_u32(off)
    if t is None: break
    if max(t) < 1000:
        continue
    s = score(t)
    if s < 500:
        best.append(("u32", off, None, s))

best.sort(key=lambda x: x[3])
print("Top candidates:")
for row in best[:20]:
    print(row)