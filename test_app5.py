import sys
sys.path.append("/Users/l/project/8888")
from app import bot_status, hist_metrics
print(hist_metrics("/Users/l/project/8404/data/trade_history.csv", "2026-09-13", 1)["entries_by_period"])
