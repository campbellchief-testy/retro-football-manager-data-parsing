from pathlib import Path
import re

data = Path("../SCOT-94.DAT").read_bytes()
text = data.decode("cp437", errors="ignore")

# Find long runs of letters/apostrophes/hyphens (the “name blobs”)
runs = [(m.start(), m.end(), m.group())
        for m in re.finditer(r"[A-Za-z'\-]{500,}", text)]

# Pick the run that contains Diamond
start, end, blob = next(r for r in runs if "Diamond" in r[2])

def split_names(s: str):
    # split when an Uppercase follows a lowercase (CamelCase boundary). 
    parts = []
    cur = s[0]
    for i, ch in enumerate(s[1:], 1):
        prev = s[i-1]
        if ch.isupper() and prev.islower():
            # don't split MacManus into Mac + Manus
            if cur.endswith("Mac"):
                cur += ch
                continue
            parts.append(cur)
            cur = ch
        else:
            cur += ch
    parts.append(cur)

    # merge Mc + Xxxxx back into McXxxxx
    merged = []
    i = 0
    while i < len(parts):
        if parts[i] == "Mc" and i + 1 < len(parts):
            merged.append("Mc" + parts[i+1])
            i += 2
        else:
            merged.append(parts[i])
            i += 1
    return merged

names = split_names(blob)

print("Blob offset range:", start, end)
print("Diamond in names?", "Diamond" in names)
print("Example around Diamond:")
i = names.index("Diamond")
print(names[i-5:i+6])