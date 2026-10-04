import json
import csv
from datetime import datetime

bot = "8401"
stats_path = f"/Users/l/project/{bot}/data/stats.json"
csv_path = f"/Users/l/project/{bot}/data/trade_history.csv"

with open(stats_path, "r") as f:
    stats = json.load(f)
    
perf_start_str = stats.get("perf_start_time", "2000-01-01 00:00:00")
perf_start_dt = datetime.strptime(perf_start_str, "%Y-%m-%d %H:%M:%S")

print(f"Perf start: {perf_start_dt}")

with open(csv_path, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    count = 0
    for row in reader:
        ts_str = row.get("시간", "")
        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        if ts >= perf_start_dt:
            count += 1
            if count <= 2:
                print(row)
    print(f"Total valid trades found: {count}")
