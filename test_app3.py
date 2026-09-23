import sys
sys.path.append("/Users/l/project/8888")
from app import calc_bot_metrics

res = calc_bot_metrics("/Users/l/project/8404", {})
print(res.keys())
