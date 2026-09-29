import sys, os, time
sys.path.insert(0, '/Users/l/project/8888')
from app import hist_metrics

res4 = hist_metrics("/Users/l/project/8404/data/trade_history.csv", "2026-09-28 00:00:00", 1)
print("8404 entries:", res4.get("entries_by_period"))

res9 = hist_metrics("/Users/l/project/8409/data/trade_history.csv", "2026-09-28 00:00:00", 1)
print("8409 entries:", res9.get("entries_by_period"))
