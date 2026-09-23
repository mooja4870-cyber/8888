import sys
import re

# 1. Patch app.py
app_path = "/Users/l/project/8404/app.py"
with open(app_path, "r") as f:
    content = f.read()

# Replace getenv hardcodings
content = content.replace('os.getenv("BINANCE_API_KEY", "")', 'os.getenv("OKX_API_KEY", "") if str(CFG.EXCHANGE_ID).lower()=="okx" else os.getenv("BINANCE_API_KEY", "")')
content = content.replace('os.getenv("BINANCE_SECRET_KEY", "")', 'os.getenv("OKX_SECRET_KEY", "") if str(CFG.EXCHANGE_ID).lower()=="okx" else os.getenv("BINANCE_SECRET_KEY", "")')
content = content.replace('os.getenv("BINANCE_PASSPHRASE", "")', 'os.getenv("OKX_PASSPHRASE", "") if str(CFG.EXCHANGE_ID).lower()=="okx" else os.getenv("BINANCE_PASSPHRASE", "")')

with open(app_path, "w") as f:
    f.write(content)


# 2. Patch core/engine.py
engine_path = "/Users/l/project/8404/core/engine.py"
with open(engine_path, "r") as f:
    content = f.read()

# Add OKXClient import
content = content.replace('from core.exchange import BinanceClient', 'from core.exchange import BinanceClient, OKXClient')

# Replace instantiation
old_inst = 'self.client = BinanceClient(api_key, secret_key, passphrase)'
new_inst = '''if str(CFG.EXCHANGE_ID).lower() == "okx":
                    self.client = OKXClient(api_key, secret_key, passphrase)
                else:
                    self.client = BinanceClient(api_key, secret_key, passphrase)'''
content = content.replace(old_inst, new_inst)

with open(engine_path, "w") as f:
    f.write(content)

print("Patched app.py and engine.py")
