import sys
sys.path.append("/Users/l/project/8888")
from app import bot_status
res = bot_status("/Users/l/project/8404", 8404, "okx")
print(res.get("entries_by_period"))
