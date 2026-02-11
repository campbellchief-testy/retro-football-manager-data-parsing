#!/usr/bin/env python3
"""
SCOT-94.DAT extractor (1994 DOS football game)

What this script does
---------------------
1) Extracts Team List A from 16-byte "slot" strings (length-prefixed).
2) Tokenises the main player-name blob and exports squads:
   - Dataset A: 21 surnames per team (team indices >= 7).
3) Extracts a second team list (Team List B) from a packed Pascal-style region
   and exports squads:
   - Dataset B: 16 surnames per team (mapped by order).
4) NEW: Exports raw per-team attribute tables found near the early header region,
   including several 64-entry byte tables and a 64-entry uint16 table.

Outputs
-------
- teamlist_A_21_squads.csv
- teamlist_B_16_squads.csv
- team_attributes_raw.csv   <-- NEW (raw fields; you can label them once decoded)

Notes
-----
This is pragmatic reverse engineering. The team-attribute export is intentionally
"raw": it dumps candidate per-team fields so you can correlate them with the in-game UI.
"""

from __future__ import annotations

import csv
import re
import struct
import sys
from pathlib import Path
from typing import List, Optional, Tuple, Dict

# ----------------------------
# Constants (empirically derived)
# ----------------------------

TEAM_COUNT = 64
TEAM_TABLE_OFFSET = 6  # 16-byte slot strings

# Main "name blob" bytes that contain concatenated surnames (empirical)
PLAYER_BLOB_START = 16300
PLAYER_BLOB_END = 42299

# Dataset A squad slicing (empirical; anchored using Celtic/Rangers names)
DATASET_A_START_TEAM_INDEX = 7
DATASET_A_SQUAD_SIZE = 21
DATASET_A_TOKEN_OFFSET = -2

# Team List B packed string region (empirical; includes "Aberdeen" etc.)
TEAMLIST_B_SCAN_MIN = 1200
TEAMLIST_B_SCAN_MAX = 3000

# Dataset B squad slicing (empirical; 16-name blocks)
DATASET_B_SQUAD_SIZE = 16
DATASET_B_TOKEN_OFFSET = 10

# Candidate team-attribute tables (empirical)
# These are NOT fully decoded yet; they are dumped to CSV for correlation.
ATTR_B1_OFFSET = 0x0C20  # 64 x u8
ATTR_U16_OFFSET = 0x0C60  # 64 x u16 little-endian (unknown meaning; sometimes correlates with "capacity-ish")
ATTR_B2_OFFSET = 0x0C80  # 64 x u8
ATTR_B3_OFFSET = 0x0CC0  # 64 x u8
ATTR_B4_OFFSET = 0x0CE0  # 64 x u8 (often ASCII-ish)

ALLOWED_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz '-.")
NAME_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]{1,23}$")


# ----------------------------
# Parsing helpers
# ----------------------------

def is_printable_name_bytes(b: bytes) -> bool:
    """ASCII-ish name bytes only: A-Z a-z space apostrophe hyphen dot."""
    for c in b:
        if (65 <= c <= 90) or (97 <= c <= 122) or (c in (32, 39, 45, 46)):
            continue
        return False
    return True


def read_slot16(data: bytes, off: int) -> Optional[str]:
    """16-byte Pascal-ish slot: [len][text...][padding...]"""
    if off + 16 > len(data):
        return None
    blk = data[off : off + 16]
    L = blk[0]
    if not (1 <= L <= 15):
        return None
    raw = blk[1 : 1 + L]
    s = raw.decode("cp437", errors="ignore").strip()
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


def extract_pascal_strings(data: bytes, min_len: int = 3, max_len: int = 24) -> List[Tuple[int, str]]:
    """Scan bytewise for Pascal-like [len][text] strings."""
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


def tokenize_mixed(s: str) -> List[str]:
    """
    Tokenise a mixed blob where names are concatenated and/or space separated.
    Rules:
      - keep letters, apostrophes, hyphens
      - split on non-name chars
      - split CamelCase boundaries (lower->Upper) to break glued surnames
      - merge Mc + Xxxx and Mac + Xxxx
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

    # merge Mc + X
    merged: List[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "Mc" and i + 1 < len(tokens):
            merged.append("Mc" + tokens[i + 1])
            i += 2
        else:
            merged.append(tokens[i])
            i += 1

    # merge Mac + X
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



def write_csv(path: Path, header: List[str], rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            path.unlink()
        except Exception:
            # fall back to truncating
            pass
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)



# ----------------------------
# Team attribute extraction (raw)
# ----------------------------

def extract_team_attributes_raw(data: bytes, teams: List[str]) -> List[Dict]:
    """
    Dump several candidate per-team attribute fields.
    These offsets were discovered empirically; meaning is TBD.
    """
    rows: List[Dict] = []
    for idx, name in enumerate(teams[:TEAM_COUNT]):
        b1 = data[ATTR_B1_OFFSET + idx] if ATTR_B1_OFFSET + idx < len(data) else None
        b2 = data[ATTR_B2_OFFSET + idx] if ATTR_B2_OFFSET + idx < len(data) else None
        b3 = data[ATTR_B3_OFFSET + idx] if ATTR_B3_OFFSET + idx < len(data) else None
        b4 = data[ATTR_B4_OFFSET + idx] if ATTR_B4_OFFSET + idx < len(data) else None

        u16 = None
        u16_off = ATTR_U16_OFFSET + idx * 2
        if u16_off + 2 <= len(data):
            u16 = struct.unpack_from("<H", data, u16_off)[0]

        rows.append({
            "team_index": idx,
            "team_name": name,
            "b1_u8": b1,
            "u16_le": u16,
            "b2_u8": b2,
            "b3_u8": b3,
            "b4_u8": b4,
            "b4_ascii": chr(b4) if isinstance(b4, int) and 32 <= b4 <= 126 else "",
        })
    return rows



# ----------------------------
# Numeric table solver (for decoding attributes like stadium capacity)
# ----------------------------

def _mean_abs_error(pred: List[int], truth: Dict[int, int]) -> float:
    err = 0.0
    for idx, val in truth.items():
        err += abs(pred[idx] - val)
    return err / max(1, len(truth))

def solve_u16_scaled_tables(
    data: bytes,
    n: int,
    truth: Dict[int, int],
    scales: List[int],
    search_start: int = 0,
    search_end: Optional[int] = None,
    step: int = 1,
) -> List[Dict]:
    """Scan for contiguous little-endian uint16 tables of length n (optionally scaled) and score vs truth anchors."""
    if search_end is None:
        search_end = len(data)
    byte_len = 2 * n
    out: List[Dict] = []
    end = min(search_end, len(data) - byte_len)
    fmt = "<" + "H" * n
    for off in range(search_start, end, step):
        try:
            vals = struct.unpack_from(fmt, data, off)
        except Exception:
            continue
        mx = max(vals)
        if mx == 0:
            continue
        for k in scales:
            pred = [v * k for v in vals]
            mae = _mean_abs_error(pred, truth)
            out.append({
                "kind": f"u16_x{k}",
                "offset": off,
                "scale": k,
                "mae": mae,
                "min": int(min(pred)),
                "max": int(max(pred)),
            })
    out.sort(key=lambda r: r["mae"])
    return out

def solve_u32_tables(
    data: bytes,
    n: int,
    truth: Dict[int, int],
    search_start: int = 0,
    search_end: Optional[int] = None,
    step: int = 1,
) -> List[Dict]:
    """Scan for contiguous little-endian uint32 tables of length n and score vs truth anchors."""
    if search_end is None:
        search_end = len(data)
    byte_len = 4 * n
    out: List[Dict] = []
    end = min(search_end, len(data) - byte_len)
    fmt = "<" + "I" * n
    for off in range(search_start, end, step):
        try:
            vals = struct.unpack_from(fmt, data, off)
        except Exception:
            continue
        mx = max(vals)
        if mx < 1000:
            continue
        pred = list(vals)
        mae = _mean_abs_error(pred, truth)
        out.append({
            "kind": "u32",
            "offset": off,
            "scale": 1,
            "mae": mae,
            "min": int(min(pred)),
            "max": int(max(pred)),
        })
    out.sort(key=lambda r: r["mae"])
    return out


# ----------------------------
# Main extraction logic
# ----------------------------

def main(dat_path: str) -> int:
    data = Path(dat_path).read_bytes()

    # Team List A: first slot16 table (typically starts at offset 6)
    tables = find_slot16_tables(data)
    if not tables:
        print("ERROR: No 16-byte slot string table found.")
        return 2
    team_table_a = tables[0]

    teamsA = [name for _, name in team_table_a[:TEAM_COUNT]]
    if len(teamsA) < TEAM_COUNT:
        # pad if necessary
        teamsA += [""] * (TEAM_COUNT - len(teamsA))

    # Tokenise name blob
    blob_text = data[PLAYER_BLOB_START:PLAYER_BLOB_END].decode("cp437", errors="ignore")
    tokens = tokenize_mixed(blob_text)

    # Dataset A squads (21 per team, aligned for indices >= 7)
    def squadA(team_index: int) -> Optional[List[str]]:
        t = team_index - DATASET_A_START_TEAM_INDEX
        start = DATASET_A_TOKEN_OFFSET + t * DATASET_A_SQUAD_SIZE
        end = start + DATASET_A_SQUAD_SIZE
        if start < 0 or end > len(tokens):
            return None
        return tokens[start:end]

    rowsA: List[Dict] = []
    for idx, tname in enumerate(teamsA):
        if idx < DATASET_A_START_TEAM_INDEX:
            continue
        sq = squadA(idx)
        if not sq:
            continue
        rec = {"team_index": idx, "team_name": tname}
        for i in range(DATASET_A_SQUAD_SIZE):
            rec[f"p{i+1}"] = sq[i]
        rowsA.append(rec)

    output_dir = Path(dat_path).resolve().parent

    outA = output_dir / "teamlist_A_21_squads.csv"
    headerA = ["team_index", "team_name"] + [f"p{i+1}" for i in range(DATASET_A_SQUAD_SIZE)]
    write_csv(outA, headerA, rowsA)

    # Team List B: packed Pascal-ish strings in scan window
    pas = extract_pascal_strings(data)
    cand = [(off, s) for off, s in pas if TEAMLIST_B_SCAN_MIN <= off <= TEAMLIST_B_SCAN_MAX]

    seen = set()
    teamsB: List[Tuple[int, str]] = []
    for off, s in cand:
        key = s.lower()
        if key in seen:
            continue
        if len(s) < 4:
            continue
        if any(k in s.upper() for k in ("LEAGUE", "DIVISION")):
            continue
        seen.add(key)
        teamsB.append((off, s))

    # Dataset B squads (16-name blocks from token offset 10)
    blocksB: List[List[str]] = []
    for bstart in range(DATASET_B_TOKEN_OFFSET, len(tokens), DATASET_B_SQUAD_SIZE):
        bend = bstart + DATASET_B_SQUAD_SIZE
        if bend > len(tokens):
            break
        blk = tokens[bstart:bend]
        ok = sum(1 for t in blk if NAME_TOKEN_RE.fullmatch(t)) >= 12
        if ok:
            blocksB.append(blk)

    rowsB: List[Dict] = []
    for i, (_, name) in enumerate(teamsB):
        if i >= len(blocksB):
            break
        blk = blocksB[i]
        rec = {"team_index": i, "team_name": name}
        for j in range(DATASET_B_SQUAD_SIZE):
            rec[f"p{j+1}"] = blk[j]
        rowsB.append(rec)

    outB = output_dir / "teamlist_B_16_squads.csv"
    headerB = ["team_index", "team_name"] + [f"p{i+1}" for i in range(DATASET_B_SQUAD_SIZE)]
    write_csv(outB, headerB, rowsB)

    # Optional: try to solve stadium capacity tables using known anchors.
    # Run with: python scot94_extract_with_attrs_and_solver.py SCOT-94.DAT --solve-capacity
    if "--solve-capacity" in sys.argv:
        # Dataset A anchors (team indices in the 64-team list)
        truthA = {
            30: 30000,  # Seraing
            22: 44000,  # AS Roma
            15: 44000,  # Kaiserslautern
            38: 86000,  # AC Milan
            36: 83000,  # Lazio
        }

        # Dataset B anchors (indices in extracted Team List B ordering)
        truthB: Dict[int, int] = {}
        name_to_idxB = {name.upper(): i for i, (_, name) in enumerate(teamsB)}
        for nm, cap in [("Parma", 42000), ("Aberdeen", 22000), ("Dundee", 16000), ("Falkirk", 14000)]:
            if nm.upper() in name_to_idxB:
                truthB[name_to_idxB[nm.upper()]] = cap

        scales = [1, 2, 4, 5, 10, 20, 25, 50, 100]

        candA = solve_u16_scaled_tables(data, TEAM_COUNT, truthA, scales, step=1)
        candA32 = solve_u32_tables(data, TEAM_COUNT, truthA, step=1)
        topA = (candA[:25] + candA32[:25])
        topA.sort(key=lambda r: r["mae"])

        topB: List[Dict] = []
        if len(truthB) >= 3 and len(teamsB) >= 20:
            nB = len(teamsB)
            candB = solve_u16_scaled_tables(data, nB, truthB, scales, step=1)
            candB32 = solve_u32_tables(data, nB, truthB, step=1)
            topB = (candB[:25] + candB32[:25])
            topB.sort(key=lambda r: r["mae"])

        solver_out = output_dir / "capacity_solver_candidates.csv"
        rows: List[Dict] = []
        for r in topA[:20]:
            rows.append({"dataset": "A", **r})
        for r in topB[:20]:
            rows.append({"dataset": "B", **r})

        write_csv(solver_out, ["dataset", "kind", "offset", "scale", "mae", "min", "max"], rows)
        print(f"Wrote: {solver_out} (rows={len(rows)})")


    # NEW: Team attributes (raw dump)
    attr_rows = extract_team_attributes_raw(data, teamsA)
    outAttr = output_dir / "team_attributes_raw.csv"
    headerAttr = ["team_index", "team_name", "b1_u8", "u16_le", "b2_u8", "b3_u8", "b4_u8", "b4_ascii"]
    write_csv(outAttr, headerAttr, attr_rows)

    print(f"Wrote: {outA} (rows={len(rowsA)})")
    print(f"Wrote: {outB} (rows={len(rowsB)})")
    print(f"Wrote: {outAttr} (rows={len(attr_rows)})")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scot94_extract_with_attrs.py /path/to/SCOT-94.DAT")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
