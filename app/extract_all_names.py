#!/usr/bin/env python3
"""
Extract (first, last) names from old DOS-era .DAT files.

Handles:
  A) 16-byte Pascal-ish string slots: [len][text...][padding...]
  B) Concatenated name blobs: AndersonDiamondMcNaughton... (CamelCase split)

Outputs:
  - names_pairs.csv: inferred first/last pairs
  - names_singles.txt: leftover plausible name tokens (unpaired)

Notes:
  - Pairing is heuristic. For best results, provide a custom first-name list.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


# --- minimal built-in first-name set (extend via --firstnames) ---
DEFAULT_FIRSTNAMES = {
    # UK/IE common
    "Alan","Alastair","Alex","Andrew","Anthony","Barry","Ben","Billy","Brian","Callum","Carl",
    "Charlie","Chris","Colin","Craig","Darren","David","Dean","Derek","Duncan","Eddie","Euan",
    "Gavin","Gordon","Graham","Grant","Gary","George","Harry","Iain","Ian","Jack","James","Jamie",
    "Jason","John","Jordan","Kevin","Kyle","Lee","Lewis","Liam","Mark","Martin","Matt","Matthew",
    "Michael","Mick","Neil","Niall","Nick","Paul","Peter","Robert","Rob","Ross","Ryan","Sam",
    "Scott","Sean","Simon","Steven","Stephen","Stuart","Thomas","Tom","Tony","Will","William",
    # broader European / common football
    "Adrian","Alberto","Alejandro","Andreas","Anton","Antonio","Carlos","Cesar","Cristian","Daniel",
    "Diego","Emil","Erik","Fabio","Felipe","Fernando","Fran","Francesco","Henrik","Ivan","Javier",
    "Joao","Johan","Jose","Juan","Julian","Karel","Luca","Marco","Mario","Miguel","Nikola",
    "Oscar","Pablo","Pedro","Rafael","Ricardo","Roberto","Sergio","Stefan","Viktor",
}

# Long runs of letters/apostrophes/hyphens (typical "name blobs")
NAME_RUN_RE = re.compile(r"[A-Za-z'\-]{200,}")

# Acceptable token characters for "single name" candidates
TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z'\-]{1,23}$")


@dataclass(frozen=True)
class Token:
    value: str
    source: str   # "slot16" or "blob"
    offset: int   # approximate byte/text offset


def load_firstnames(path: Optional[str]) -> set[str]:
    names = set(DEFAULT_FIRSTNAMES)
    if not path:
        return names
    p = Path(path)
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # allow "john" or "John"
        names.add(s[:1].upper() + s[1:].lower())
    return names


def is_plausible_token(s: str) -> bool:
    s = s.strip()
    if not (2 <= len(s) <= 24):
        return False
    if not TOKEN_RE.match(s):
        return False
    # avoid obvious non-names that appear in football files
    blacklist = {
        "Division","Premier","League","Scottish","Reserve","United","City",
        "Rovers","Athletic","County","Football","Club",
    }
    if s in blacklist:
        return False
    # reject long ALLCAPS blocks (headers)
    if s.isupper() and len(s) > 5:
        return False
    return True


def split_concatenated_names(blob: str) -> List[str]:
    """
    Split concatenated names at lower->Upper boundaries.
    Preserve MacXxxx and re-merge Mc + Xxxx if it was split.
    """
    if not blob:
        return []

    parts: List[str] = []
    cur = blob[0]

    for i in range(1, len(blob)):
        ch = blob[i]
        prev = blob[i - 1]

        if ch.isupper() and prev.islower():
            # don't split MacPherson into Mac + Pherson
            if cur.endswith("Mac") or cur.endswith("Mc"):
                cur += ch
                continue
            parts.append(cur)
            cur = ch
        else:
            cur += ch
    parts.append(cur)

    # merge Mc + Xxxx back into McXxxx
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


def extract_slot16_tokens(data: bytes, start: int = 0, recsize: int = 16) -> Iterable[Token]:
    """
    Walk the file in 16-byte steps and decode any plausible Pascal-ish strings.
    Many DOS sports files store strings as: [len][text...][padding]
    """
    maxlen = recsize - 1
    for off in range(start, len(data) - recsize + 1, recsize):
        blk = data[off:off + recsize]
        L = blk[0]
        if not (1 <= L <= maxlen):
            continue
        raw = blk[1:1 + L]
        try:
            s = raw.decode("cp437", errors="ignore").strip()
        except Exception:
            continue
        
        # Often these are single tokens (club names, surnames, etc.)
        if is_plausible_token(s):
            print("Read: "+s)
            yield Token(s, "slot16", off)


def extract_blob_tokens(text: str) -> Iterable[Token]:
    """
    Find long A-Za-z'- runs and split into tokens.
    Offset is text-index (not exact byte offset), but useful for debugging.
    """
    for m in NAME_RUN_RE.finditer(text):
        blob = m.group()
        base = m.start()
        for t in split_concatenated_names(blob):
            t = t.strip()
            if is_plausible_token(t):
                yield Token(t, "blob", base)


def infer_pairs(tokens: Sequence[Token], firstnames: set[str]) -> Tuple[List[Tuple[str, str, str, int]], List[Token]]:
    """
    Heuristic pairing:
      - If token[i] is a known first name and token[i+1] looks like a surname -> pair.
      - Otherwise leave as single.
    """
    pairs: List[Tuple[str, str, str, int]] = []
    singles: List[Token] = []

    i = 0
    while i < len(tokens):
        t = tokens[i]
        v = t.value[:1].upper() + t.value[1:]  # normalise case a bit

        if v in firstnames and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            # simple surname sanity: not also a first name (still allow if you want)
            if is_plausible_token(nxt.value):
                pairs.append((v, nxt.value, t.source, t.offset))
                i += 2
                continue

        singles.append(t)
        i += 1

    return pairs, singles


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract first/last names from a DOS-era binary .DAT file.")
    ap.add_argument("input", help="Path to .DAT file")
    ap.add_argument("--firstnames", help="Optional UTF-8 text file with one first name per line", default=None)
    ap.add_argument("--slot-start", type=int, default=0, help="Start offset for 16-byte slot scan (default: 0)")
    ap.add_argument("--minrun", type=int, default=200, help="Min length of alpha-run to treat as blob (default: 200)")
    ap.add_argument("--pairs-out", default="names_pairs.csv", help="CSV output for inferred pairs")
    ap.add_argument("--singles-out", default="names_singles.txt", help="Text output for unpaired tokens")
    args = ap.parse_args()

    global NAME_RUN_RE
    NAME_RUN_RE = re.compile(rf"[A-Za-z'\-]{{{args.minrun},}}")

    data = Path(args.input).read_bytes()
    text = data.decode("cp437", errors="ignore")
    firstnames = load_firstnames(args.firstnames)

    # Extract tokens from both encodings
    slot_tokens = list(extract_slot16_tokens(data, start=args.slot_start))
    blob_tokens = list(extract_blob_tokens(text))

    # Combine while keeping rough file order for better pairing
    all_tokens = sorted(slot_tokens + blob_tokens, key=lambda t: t.offset)

    # Infer pairs
    pairs, singles = infer_pairs(all_tokens, firstnames)

    # De-duplicate pairs + singles
    pair_seen = set()
    pairs_unique: List[Tuple[str, str, str, int]] = []
    for p in pairs:
        key = (p[0], p[1])
        if key in pair_seen:
            continue
        pair_seen.add(key)
        pairs_unique.append(p)

    single_seen = set()
    singles_unique: List[Token] = []
    for s in singles:
        if s.value in single_seen:
            continue
        single_seen.add(s.value)
        singles_unique.append(s)

    # Write outputs
    with open(args.pairs_out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["first", "last", "source", "offset"])
        w.writerows(pairs_unique)

    Path(args.singles_out).write_text(
        "\n".join(sorted((t.value for t in singles_unique), key=lambda x: x.lower())) + "\n",
        encoding="utf-8"
    )

    print(f"Total tokens: {len(all_tokens)}")
    print(f"Inferred pairs: {len(pairs_unique)} -> {args.pairs_out}")
    print(f"Unpaired singles: {len(singles_unique)} -> {args.singles_out}")

    # Quick sanity checks
    for probe in ["Diamond", "Rangers", "Celtic", "Hearts"]:
        present = any(t.value == probe for t in all_tokens)
        print(f"{probe}: {present}")


if __name__ == "__main__":
    main()