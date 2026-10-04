import re

with open("/Users/l/project/8888/discord_alert.py", "r", encoding="utf-8") as f:
    content = f.read()

helper_code_new = """
def _get_tuned_metrics(b_item, tuning_time_str="2026-09-30 13:17:00"):
    import copy, csv, os, datetime
    new_b = copy.deepcopy(b_item)
    bot_name = new_b.get("name")
    if not bot_name:
        return new_b
    tuning_time = datetime.datetime.strptime(tuning_time_str, "%Y-%m-%d %H:%M:%S")
    
    csv_path = f"/Users/l/project/{bot_name}/data/trade_history.csv"
    wins, losses = 0, 0
    sun20_w, sun20_l, yeok20_w, yeok20_l = 0, 0, 0, 0
    pnl = 0.0
    seq = ""
    last_w, last_l = 0, 0
    
    if os.path.exists(csv_path):
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) < 7: continue
                    if row[2] == '청산':
                        t_str = row[0]
                        t_dt = datetime.datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")
                        if t_dt >= tuning_time:
                            p = float(row[6])
                            pnl += p
                            is_sun = True
                            if len(row) >= 14 and row[13] == '역방향':
                                is_sun = False
                                
                            if p > 0:
                                wins += 1
                                seq = "O" + seq
                                last_w = 0
                                last_l += 1
                                if is_sun: sun20_w += 1
                                else: yeok20_w += 1
                            else:
                                losses += 1
                                seq = "x" + seq
                                last_l = 0
                                last_w += 1
                                if is_sun: sun20_l += 1
                                else: yeok20_l += 1
        except Exception:
            pass
            
    current_bal = float(new_b.get("ex_balance") or ((new_b.get("seed") or 0) + (new_b.get("total") or 0)))
    new_seed = current_bal - pnl
    if new_seed <= 0:
        new_seed = current_bal
        
    new_b["seed"] = new_seed
    new_b["total"] = pnl
    new_b["ex_balance"] = current_bal
    new_b["wins"] = wins
    new_b["losses"] = losses
    new_b["seq"] = seq
    new_b["since_w"] = last_w
    new_b["since_l"] = last_l
    
    # Force 0 for the output fields
    new_b["sun20_w"] = sun20_w
    new_b["sun20_l"] = sun20_l
    new_b["yeok20_w"] = yeok20_w
    new_b["yeok20_l"] = yeok20_l
    new_b["sun20"] = sun20_w + sun20_l
    new_b["yeok20"] = yeok20_w + yeok20_l
    
    now = datetime.datetime.now()
    diff = (now - tuning_time).total_seconds() / 86400
    new_b["days"] = diff if diff > 0.01 else 0.01
    
    cum_ret = (pnl / new_seed * 100) if new_seed > 0 else 0
    new_b["daily_ret"] = round(cum_ret / new_b["days"], 4)
    new_b["entries_by_period"] = {"1h": 0, "4h": 0, "12h": 0, "24h": 0}
    return new_b
"""

# We need to replace the old _get_tuned_metrics with the new one.
# It starts at "def _get_tuned_metrics" and ends right before "def tick(data"
start_idx = content.find("def _get_tuned_metrics")
end_idx = content.find("def tick(data", start_idx)

if start_idx != -1 and end_idx != -1:
    content = content[:start_idx] + helper_code_new.strip() + "\n\n\n" + content[end_idx:]
    with open("/Users/l/project/8888/discord_alert.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Patch 2 applied.")
else:
    print("Failed to find boundaries.")

