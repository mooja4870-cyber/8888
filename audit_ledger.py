import os
import json
import csv
from datetime import datetime

bots = ["8401", "8402", "8403", "8404", "8405", "8406", "8407", "8408", "8409", "8410"]

print("==========================================")
print(" 🛡️ Ledger Integrity Deep Audit Report 🛡️ ")
print("==========================================")

for bot in bots:
    stats_path = f"/Users/l/project/{bot}/data/stats.json"
    csv_path = f"/Users/l/project/{bot}/data/trade_history.csv"
    
    if not os.path.exists(stats_path) or not os.path.exists(csv_path):
        continue
        
    with open(stats_path, "r") as f:
        stats = json.load(f)
        
    perf_start_str = stats.get("perf_start_time", "2000-01-01 00:00:00")
    try:
        perf_start_dt = datetime.strptime(perf_start_str, "%Y-%m-%d %H:%M:%S")
    except:
        perf_start_dt = datetime.min
        
    stats_total_pnl = stats.get("total_pnl_usdt", 0.0)
    stats_trades = stats.get("total_trades", 0)
    stats_wins = stats.get("total_wins", 0)
    stats_losses = stats.get("total_losses", 0)
    
    csv_pnl = 0.0
    csv_trades = 0
    csv_wins = 0
    csv_losses = 0
    
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = row.get("시간", "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except:
                    continue
                    
                if ts >= perf_start_dt:
                    pnl_str = row.get("수익(USDT)", "0.0")
                    if pnl_str == "":
                        pnl_str = "0.0"
                    pnl = float(pnl_str)
                    
                    status = row.get("유형", "")
                    
                    if status == "청산":
                        csv_pnl += pnl
                        csv_trades += 1
                        if pnl > 0:
                            csv_wins += 1
                        elif pnl < 0:
                            csv_losses += 1
                        else:
                            csv_losses += 1 # 0 is usually loss or break-even mapped to loss in stats
    except Exception as e:
        print(f"[{bot}] Error parsing CSV: {e}")
        continue
        
    diff_pnl = abs(stats_total_pnl - csv_pnl)
    status_icon = "✅" if diff_pnl < 0.05 and stats_trades == csv_trades else "❌ Mismatch!"
    
    print(f"[{bot}] {status_icon}")
    print(f"   Stats JSON : PNL={stats_total_pnl:.4f} | Trades={stats_trades} (W:{stats_wins} L:{stats_losses})")
    print(f"   CSV Ledger : PNL={csv_pnl:.4f} | Trades={csv_trades} (W:{csv_wins} L:{csv_losses})")
    if diff_pnl >= 0.05:
        print(f"   ⚠️ PNL DIFF = {diff_pnl:.4f}")
    if stats_trades != csv_trades:
        print(f"   ⚠️ TRADES DIFF = {abs(stats_trades - csv_trades)}")

print("==========================================")
