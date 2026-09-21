import sys
sys.path.insert(0, '/Users/l/project/8888')
import app
import os

data = app.collect()
bots = data.get("bots", [])

print("=== 봇 전체 포지션 상태 상세 ===")
for b in bots:
    bid = b.get("name")
    holding = b.get("holding")
    ex_long = b.get("ex_poslong", 0)
    ex_short = b.get("ex_posshort", 0)
    pos_count = ex_long + ex_short
    err = b.get("ex_err")
    print(f"[{bid}] holding={holding}, positions={pos_count} (L:{ex_long}, S:{ex_short}), err={err}")

