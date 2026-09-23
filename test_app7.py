import sys
sys.path.append("/Users/l/project/8888")
from app import hist_metrics
try:
    m = hist_metrics("/Users/l/project/8404/data/trade_history.csv", "2026-09-13", 1)
    print("M returned entries:", m["entries_by_period"])
except Exception as e:
    print("Exception", e)
