import re

path = "/Users/l/project/8407/core/api_keys.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace('"apikey": "BINANCE_API_KEY",', '"binance_api_key": "BINANCE_API_KEY",\n    "apikey": "BINANCE_API_KEY",')
content = content.replace('"secretkey": "BINANCE_SECRET_KEY",', '"binance_secret_key": "BINANCE_SECRET_KEY",\n    "secretkey": "BINANCE_SECRET_KEY",')
content = content.replace('required = ("BINANCE_API_KEY", "BINANCE_SECRET_KEY", "BINANCE_PASSPHRASE")', 'required = ("BINANCE_API_KEY", "BINANCE_SECRET_KEY")')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done patching api_keys.py again")
