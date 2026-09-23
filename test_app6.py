import sys
sys.path.append("/Users/l/project/8888")
from app import bot_status
res = bot_status("/Users/l/project/8404", 8404, "okx")
print("entries_by_period:", res.get("entries_by_period"))
print("1h:", res.get("entries_by_period", {}).get("1h"))
print("4h:", res.get("entries_by_period", {}).get("4h"))
