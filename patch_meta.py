import json
import os

bots_15m = ["8401", "8403", "8406"]
bots_1h = ["8407", "8409"]

for bot in bots_15m + bots_1h:
    filepath = f"/Users/l/project/{bot}/config.json"
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            cfg = json.load(f)
            
        tf = "15m" if bot in bots_15m else "1h"
        sl = "2.5" if bot in bots_15m else "4.0"
        
        cfg["DASHBOARD_META"] = {
            "strategy": f"BB Mean Reversion ({tf})",
            "indicators": "BB, ATR, RSI",
            "sl_str": f"ATR×{sl}",
            "tp_str": "SMA/BB Mid"
        }
        
        with open(filepath, "w") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
            
        print(f"Patched {bot}")
