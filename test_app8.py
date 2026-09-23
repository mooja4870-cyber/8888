import sys
sys.path.append("/Users/l/project/8888")
from app import bot_status

# bot_status signature is bot_status(folder, port, ex)
# wait, what does it do?
res = bot_status("/Users/l/project/8404", 8404, "okx")
print("keys in res:", res.keys())
print("pos_count in res:", res.get("ex_poscount", 0))
print("perf_start in res:", res.get("perf_start"))
