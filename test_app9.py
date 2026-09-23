import sys
sys.path.append("/Users/l/project/8888")
from app import bot_status
res = bot_status("/Users/l/project/8408", 8408, "okx")
print("8408:", res.get("entries_by_period"))
