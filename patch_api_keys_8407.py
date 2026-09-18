import re

path = "/Users/l/project/8407/core/api_keys.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("OKX_API_KEY", "BINANCE_API_KEY")
content = content.replace("OKX_SECRET_KEY", "BINANCE_SECRET_KEY")
content = content.replace("OKX_PASSPHRASE", "BINANCE_PASSPHRASE")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done patching api_keys.py")
