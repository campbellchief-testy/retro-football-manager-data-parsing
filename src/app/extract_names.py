#!/usr/bin/env python3
"""
Generic extractor for player/staff names from old DOS-era binary .DAT files.

Strategy:
1) Decode bytes using CP437 (DOS Western) with errors ignored.
2) Find long runs of [A-Za-z'-] (these often store concatenated surnames).
3) Split those runs into names using CamelCase boundaries (lower->upper transitions),
   with heuristics for Mc/Mac.
4) Filter improbable tokens and deduplicate.
"""

from __future__ import annotations

import re
import csv
import argparse
from collections import Counter
from pathlib import Path
from typing import Iterable, List


NAME_RUN_RE = re.compile(r"[A-Za-z'\-]{200,}")  # adjust threshold if needed


def split_concatenated_names(blob: str) -> List[str]:
    """
    Split a concatenated surname blob like:
      'AndersonDiamondMcNaughtonO'NeilMacPherson'
    into:
      ['Anderson','Diamond','McNaughton',"O'Neil",'MacPherson']
    """
    if not blob:
        return []

    parts: List[str] = []
    cur = blob[0]

    for i in range(1, len(blob)):
        ch = blob[i]
        prev = blob[i - 1]

        # CamelCase boundary: a new name often begins at Upper following lower
        if ch.isupper() and prev.islower():
            # Heuristic: avoid splitting "MacPherson" into "Mac" + "Pherson"
            if (cur.endswith("Mac") or cur.endswith("Mc"))and len(cur) >= 3:
                cur += ch
                continue

            parts.append(cur)
            cur = ch
        else:
            cur += ch

    parts.append(cur)

    # Heuristic: merge Mc + Xxxxx back into McXxxxx (when split as "Mc" and "Naughton")
    merged: List[str] = []
    i = 0
    while i < len(parts):
        if parts[i] == "Mc" and i + 1 < len(parts) and parts[i + 1][:1].isupper():
            merged.append("Mc" + parts[i + 1])
            i += 2
        else:
            merged.append(parts[i])
            i += 1

    return merged


def is_plausible_name(token: str) -> bool:
    """
    Filter out junk tokens: too short/long, mostly punctuation, etc.
    """
    t = token.strip()
    if not (2 <= len(t) <= 24):
        return False

    # Must contain at least one letter
    if not any(c.isalpha() for c in t):
        return False

    # Reject tokens with weird punctuation patterns
    if "--" in t or "''" in t:
        return False

    # Common false positives in football data files (tweak as you discover more)
    blacklist = {
        "Division", "Premier", "League", "Scottish", "Reserve", "United", "City",
        "FC", "AFC", "Rovers", "Athletic", "County",
    }
    if t in blacklist:
        return False

    # Avoid ALLCAPS chunks (often headers) unless short (e.g., "O'Neil" isn't all caps)
    if t.isupper() and len(t) > 5:
        return False

    return True


def extract_name_candidates(text: str) -> Iterable[str]:
    """
    Find long alpha runs and split them into candidate names.
    """
    for m in NAME_RUN_RE.finditer(text):
        blob = m.group()
        # Some runs might be genuine sentences; we still try splitting
        for token in split_concatenated_names(blob):
            if is_plausible_name(token):
                yield token


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract concatenated player/staff names from DOS-era binary files.")
    ap.add_argument("input", help="Path to .DAT (or any binary) file")
    ap.add_argument("--minrun", type=int, default=200, help="Minimum length of alpha run to treat as a name blob (default: 200)")
    ap.add_argument("--out", default="names.txt", help="Output text file (default: names.txt)")
    ap.add_argument("--csv", default="names.csv", help="Optional CSV output with counts (default: names.csv)")
    ap.add_argument("--encoding", default="cp437", help="Text decoding (default: cp437)")
    args = ap.parse_args()

    global NAME_RUN_RE
    NAME_RUN_RE = re.compile(rf"[A-Za-z'\-]{{{args.minrun},}}")

    data = Path(args.input).read_bytes()

    print("Opened file:"+args.input)

    # Decode using DOS CP437; ignore undecodable bytes (common in mixed binary/text formats)
    text = data.decode(args.encoding, errors="ignore")

    counts = Counter(extract_name_candidates(text))

    # De-duplicate, sort by frequency desc then alphabetically
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))

    # Write plain list
    out_path = Path(args.out)
    out_path.write_text("\n".join([name for name, _ in items]) + "\n", encoding="utf-8")

    # Write CSV with counts
    csv_path = Path(args.csv)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "count"])
        w.writerows(items)

    print(f"Extracted {len(items)} unique candidate names")
    print(f"Wrote: {out_path}")
    print(f"Wrote: {csv_path}")

    # quick sanity check for your example
    if "Diamond" in counts:
        print(f'Found "Diamond" (count={counts["Diamond"]})')


if __name__ == "__main__":
    main()