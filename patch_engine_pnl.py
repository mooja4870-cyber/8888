import os
import re

bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]

for b in bots:
    engine_path = f"/Users/l/project/{b}/core/engine.py"
    golden_path = f"/Users/l/project/{b}/.golden/core/engine.py"
    
    if not os.path.exists(engine_path):
        print(f"Skipping {b}, no engine.py")
        continue
        
    with open(engine_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # 1. Fix contractSize NameError
    content = content.replace(
        "contract_size = float(self.client._markets[sym].get(contractSize, 1.0))",
        "contract_size = float(self.client._markets[sym].get('contractSize', 1.0))"
    )
    
    # 2. Add total_margin_est = 0.0 before the loop
    if "total_margin_est = 0.0" not in content:
        content = content.replace(
            "total_pnl = 0.0\n                        latest_exit_trade = None",
            "total_pnl = 0.0\n                        total_margin_est = 0.0\n                        latest_exit_trade = None"
        )
        
    # 3. Accumulate total_margin_est inside the loop
    if "total_margin_est += margin_est" not in content:
        content = content.replace(
            "total_pnl += grp_pnl\n                            latest_exit_trade = last_t",
            "total_pnl += grp_pnl\n                            total_margin_est += margin_est\n                            latest_exit_trade = last_t"
        )
        
    # 4. Calculate actual integrated pnl_pct_val
    if "total_margin_est > 0 else latest_pnl_pct_val" not in content:
        content = content.replace(
            "pnl = total_pnl\n                        exit_trade = latest_exit_trade\n                        pnl_pct_val = latest_pnl_pct_val",
            "pnl = total_pnl\n                        exit_trade = latest_exit_trade\n                        pnl_pct_val = (total_pnl / total_margin_est) * 100 if total_margin_est > 0 else latest_pnl_pct_val"
        )
        
    with open(engine_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    if os.path.exists(golden_path):
        with open(golden_path, "w", encoding="utf-8") as f:
            f.write(content)
            
    print(f"Patched engine.py for {b}")
