import sys
sys.path.append("/Users/l/project/8888")
from app import collect

data = collect()
bots = data.get("bots", [])
for b in bots:
    if b.get("name") in ["8404", "8408"]:
        eb = b.get("entries_by_period") or {}
        ent1 = eb.get("1h", 0)
        ent4 = eb.get("4h", 0)
        ent12 = eb.get("12h", 0)
        ent24 = eb.get("24h", 0)
        sw = b.get("since_w") or 0
        sl = b.get("since_l") or 0
        sun20_w = b.get("sun20_w", 0)
        sun20_l = b.get("sun20_l", 0)
        yeok20_w = b.get("yeok20_w", 0)
        yeok20_l = b.get("yeok20_l", 0)
        line = f"Bot {b['name']}: ({ent1:02d}/{ent4:02d}|{ent12:02d}/{ent24:02d} {sw:02d}W/{sl:02d}L : ({sun20_w}-{sun20_l})+({yeok20_w}-{yeok20_l}))"
        print(line)
        print("Raw entries_by_period:", eb)
