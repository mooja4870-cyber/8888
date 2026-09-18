import re

# Patch bot.py
path = "/Users/l/project/8407/bot.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace('os.getenv("OKX_API_KEY"', 'os.getenv("BINANCE_API_KEY"')
content = content.replace('os.getenv("OKX_SECRET_KEY"', 'os.getenv("BINANCE_SECRET_KEY"')
content = content.replace('os.getenv("OKX_PASSPHRASE"', 'os.getenv("BINANCE_PASSPHRASE"')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

# Patch app.py
path = "/Users/l/project/8407/app.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace('os.getenv("OKX_API_KEY"', 'os.getenv("BINANCE_API_KEY"')
content = content.replace('os.getenv("OKX_SECRET_KEY"', 'os.getenv("BINANCE_SECRET_KEY"')
content = content.replace('os.getenv("OKX_PASSPHRASE"', 'os.getenv("BINANCE_PASSPHRASE"')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done patching bot.py and app.py for Binance keys.")
