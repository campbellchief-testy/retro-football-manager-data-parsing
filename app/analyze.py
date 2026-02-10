from pathlib import Path

path = "../SCOT-94.DAT"
data = Path(path).read_bytes()

START = 6          # header appears to be 6 bytes in this file
RECSIZE = 16       # fixed slot size
MAXLEN = 15        # max string length stored in 1 byte

names = []
for i in range(0, 2000):  # 300 is safe; we'll stop when it stops looking like names
    off = START + i * RECSIZE
    if off + RECSIZE > len(data):
        break

    blk = data[off:off + RECSIZE]
    L = blk[0]

    if 1 <= L <= MAXLEN:
        s = blk[1:1 + L].decode("cp437", errors="replace")
    else:
        # salvage (rare): treat as raw text without length byte
        s = blk[1:].rstrip(b"\x00 ").decode("cp437", errors="replace")

    # heuristic stop: once we hit non-texty sections, bail out
    if not any(c.isalpha() for c in s):
        # if we already collected a decent list, stop
        if len(names) > 15550:
            break
        continue

    names.append(s)

# show a few and confirm key clubs exist
print("count:", len(names))
for club in ["Rangers", "Celtic", "Hearts"]:
    print(club, "->", club in names)

print(names[:30])
print(names)
