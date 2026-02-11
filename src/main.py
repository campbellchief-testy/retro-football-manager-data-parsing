from pathlib import Path
import struct

DAT_PATH = "../SCOT-94.DAT"

TEAM_TABLE_OFFSET = 6
TEAM_COUNT = 64

# Candidate attribute tables
B1_OFFSET = 0x0C20   # byte
CAP_OFFSET = 0x0C60  # uint16
B2_OFFSET = 0x0C80   # byte
B3_OFFSET = 0x0CC0   # byte
B4_OFFSET = 0x0CE0   # byte

def read_slot16(data, off):
    blk = data[off:off+16]
    L = blk[0]
    if not (1 <= L <= 15):
        return None
    return blk[1:1+L].decode("cp437", "ignore").strip()

def load_teams(data):
    teams = []
    off = TEAM_TABLE_OFFSET
    for _ in range(TEAM_COUNT):
        teams.append(read_slot16(data, off))
        off += 16
    return teams

def dump_team(data, teams, name):
    idx = teams.index(name)
    b1 = data[B1_OFFSET + idx]
    cap = struct.unpack_from("<H", data, CAP_OFFSET + idx*2)[0]
    b2 = data[B2_OFFSET + idx]
    b3 = data[B3_OFFSET + idx]
    b4 = data[B4_OFFSET + idx]
    return {
        "team": name,
        "index": idx,
        "b1": b1,
        "capacity": cap,
        "b2": b2,
        "b3": b3,
        "b4": b4,
    }

if __name__ == "__main__":
    data = Path(DAT_PATH).read_bytes()
    teams = load_teams(data)
    print(teams)
    samples = [
        "AC Milan",
        "Lazio",
        "Napoli",
        "Kaiserslautern",
    ]

    for t in samples:
        print(dump_team(data, teams, t))