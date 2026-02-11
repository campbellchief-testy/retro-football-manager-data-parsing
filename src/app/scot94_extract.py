#!/usr/bin/env python3
"""
Two Nil data extractor (1994 DOS football data)

Outputs:
  - teamlist_A_21_squads.csv  (Team List A from 16-byte slots; 21-player squads)
  - teamlist_B_16_squads.csv  (Team List B from packed Pascal-ish strings; 16-player squads)

This script uses the empirically-derived structure:
  - Team List A: 16-byte slots, starting at offset 6, 64 entries.
  - Player-name blob: bytes 16300..42299, tokenised via mixed rules.
  - Dataset A squads: 21 tokens/team, aligned with team indices >= 7 using offset -2.
  - Team List B: extracted from Pascal-ish strings in byte window 1200..3000.
  - Dataset B squads: 16-name blocks from token offset 10.

Run:
  python scot94_extract.py /path/to/SCOT-94.DAT
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


# ----------------------------
# Utility / validation helpers
# ----------------------------

ALLOWED_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz '-.")


def is_printable_name_bytes(b: bytes) -> bool:
    """ASCII-ish name bytes only: A-Z a-z space apostrophe hyphen dot."""
    for c in b:
        if (65 <= c <= 90) or (97 <= c <= 122) or (c in (32, 39, 45, 46)):
            continue
        return False
    return True


def read_slot16(data: bytes, off: int) -> Optional[str]:
    """
    16-byte Pascal-ish slot:
      [len][text...][padding...]
    """
    if off + 16 > len(data):
        return None
    blk = data[off : off + 16]
    L = blk[0]
    if not (1 <= L <= 15):
        return None
    raw = blk[1 : 1 + L]
    try:
        s = raw.decode("cp437", errors="ignore").strip()
    except Exception:
        return None
    if not s or not any(ch.isalpha() for ch in s):
        return None
    if any(ch not in ALLOWED_CHARS for ch in s):
        return None
    return s


def find_slot16_tables(data: bytes) -> List[List[Tuple[int, str]]]:
    """Find contiguous runs of valid slot16 strings."""
    tables: List[List[Tuple[int, str]]] = []
    i = 0
    while i < len(data) - 16:
        slots: List[Tuple[int, str]] = []
        off = i
        while True:
            s = read_slot16(data, off)
            if s is None:
                break
            slots.append((off, s))
            off += 16
        if len(slots) >= 8:
            tables.append(slots)
            i = off
        else:
            i += 1
    return tables


def extract_pascal_strings(
    data: bytes, min_len: int = 3, max_len: int = 24
) -> List[Tuple[int, str]]:
    """
    Scan bytewise for Pascal-like [len][text] strings.
    Used to recover the packed Team List B.
    """
    out: List[Tuple[int, str]] = []
    i = 0
    while i < len(data) - 2:
        L = data[i]
        if min_len <= L <= max_len and i + 1 + L <= len(data):
            sbytes = data[i + 1 : i + 1 + L]
            if is_printable_name_bytes(sbytes):
                s = sbytes.decode("cp437", errors="ignore").strip()
                if any(ch.isalpha() for ch in s):
                    out.append((i, s))
                i += 1 + L
                continue
        i += 1
    return out


# ----------------------------
# Tokenisation for name blobs
# ----------------------------

NAME_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]{1,23}$")


def tokenize_mixed(s: str) -> List[str]:
    """
    Tokenise a mixed blob where names are concatenated and/or space separated.
    Rules:
      - keep letters, apostrophes, hyphens
      - split on non-name chars
      - split CamelCase boundaries (lower->Upper) to break glued surnames
      - merge Mc + Xxxx and Mac + Xxxx (common Scottish prefixes)
    """
    tokens: List[str] = []
    cur = ""

    def flush() -> None:
        nonlocal cur
        if cur:
            tokens.append(cur)
            cur = ""

    for ch in s:
        if ch == " ":
            flush()
            continue
        if not (ch.isalpha() or ch in ("'", "-")):
            flush()
            continue
        if cur and ch.isupper() and cur[-1].islower():
            flush()
            cur = ch
        else:
            cur += ch
    flush()

    # merge Mc + X -> McX
    merged: List[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "Mc" and i + 1 < len(tokens):
            merged.append("Mc" + tokens[i + 1])
            i += 2
        else:
            merged.append(tokens[i])
            i += 1

    # merge Mac + X -> MacX
    merged2: List[str] = []
    i = 0
    while i < len(merged):
        if merged[i] == "Mac" and i + 1 < len(merged):
            merged2.append("Mac" + merged[i + 1])
            i += 2
        else:
            merged2.append(merged[i])
            i += 1

    return merged2


# ----------------------------
# Writers
# ----------------------------

def write_csv(path: Path, header: List[str], rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ----------------------------
# Main extraction logic
# ----------------------------

def main(dat_path: str) -> int:
    data = Path(dat_path).read_bytes()

    # 1) Team List A: first slot16 table (offset 6)
    tables = find_slot16_tables(data)
    if not tables:
        print("ERROR: No slot16 team table found.")
        return 2
    team_table_a = tables[0]  # the big 64-entry table starting at 6

    teamA = [{"team_index": i, "team_name": name, "name_slot_offset": off}
             for i, (off, name) in enumerate(team_table_a)]

    # 2) Player-name blob (empirical)
    blob_start, blob_end = 16300, 42299
    blob_text = data[blob_start:blob_end].decode("cp437", errors="ignore")
    tokens = tokenize_mixed(blob_text)

    # 3) Dataset A squads: 21 per team, offset -2, for teams with index >= 7
    start_team_index = 7
    chunkA = 21
    offsetA = -2

    def squadA(team_index: int) -> Optional[List[str]]:
        t = team_index - start_team_index
        start = offsetA + t * chunkA
        end = start + chunkA
        if start < 0 or end > len(tokens):
            return None
        return tokens[start:end]

    rowsA: List[dict] = []
    for t in teamA:
        idx = int(t["team_index"])
        if idx < start_team_index:
            continue
        sq = squadA(idx)
        if not sq:
            continue
        rec = {"team_index": idx, "team_name": t["team_name"]}
        for i in range(chunkA):
            rec[f"p{i+1}"] = sq[i]
        rowsA.append(rec)

    outA = Path("teamlist_A_21_squads.csv")
    headerA = ["team_index", "team_name"] + [f"p{i+1}" for i in range(chunkA)]
    write_csv(outA, headerA, rowsA)

    # 4) Team List B: packed Pascal-ish strings in a known region
    #    (We take the 1200..3000 window where "Newcastle Utd / Airdrionians / Aberdeen / ..." appears.)
    pas = extract_pascal_strings(data)
    cand = [(off, s) for off, s in pas if 1200 <= off <= 3000]

    # de-dup preserve order; filter obvious non-teams
    seen = set()
    teamB: List[Tuple[int, str]] = []
    for off, s in cand:
        key = s.lower()
        if key in seen:
            continue
        if len(s) < 4:
            continue
        if any(k in s.upper() for k in ("LEAGUE", "DIVISION")):
            continue
        seen.add(key)
        teamB.append((off, s))

    # 5) Dataset B squads: 16-name blocks from token offset 10
    chunkB = 16
    offsetB = 10

    # Build all plausible 16-token blocks
    blocksB: List[Tuple[int, int, List[str]]] = []
    block_id = 0
    for bstart in range(offsetB, len(tokens), chunkB):
        bend = bstart + chunkB
        if bend > len(tokens):
            break
        blk = tokens[bstart:bend]
        # basic sanity filter: mostly name-like tokens
        ok = sum(1 for t in blk if NAME_TOKEN_RE.fullmatch(t)) >= 12
        if not ok:
            continue
        blocksB.append((block_id, bstart, blk))
        block_id += 1

    # Map Team List B -> blocks in order (best effort)
    rowsB: List[dict] = []
    for i, (_, name) in enumerate(teamB):
        if i >= len(blocksB):
            break
        blk = blocksB[i][2]
        rec = {"team_index": i, "team_name": name}
        for j in range(chunkB):
            rec[f"p{j+1}"] = blk[j]
        rowsB.append(rec)

    outB = Path("teamlist_B_16_squads.csv")
    headerB = ["team_index", "team_name"] + [f"p{i+1}" for i in range(chunkB)]
    write_csv(outB, headerB, rowsB)

    print(f"Wrote: {outA}  (rows={len(rowsA)})")
    print(f"Wrote: {outB}  (rows={len(rowsB)})")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scot94_extract.py /path/to/SCOT-94.DAT")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))