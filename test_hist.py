import sys
sys.path.append("/Users/l/project/8888")
from app import hist_metrics

res = hist_metrics("/Users/l/project/8404/data/trade_history.csv", None, 1)
print(res.get("entries_by_period"))
