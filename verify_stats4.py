import json
import os

bots = ["8401", "8402", "8410"]
for b in bots:
    stats_path = f"/Users/l/project/{b}/data/stats.json"
    try:
        with open(stats_path, 'r', encoding='utf-8') as f:
            st = json.load(f)
            total_pnl = st.get("total_pnl_usdt", 0)
            seed = st.get("seed_money", 10.0)
            balance = seed + total_pnl
            print(f"[{b}] stats.json -> Total PnL: {total_pnl}, Balance: {balance}")
    except Exception as e:
        print(f"[{b}] stats error: {e}")
