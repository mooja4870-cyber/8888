import json
import os

config_path = "/Users/l/project/8401/config.json"
with open(config_path, 'r') as f:
    config = json.load(f)

config["EXCHANGE_ID"] = "okx"

# We should also translate symbols in SYMBOL_WHITELIST if they are in Binance format (e.g., SOL/USDT:USDT -> SOL-USDT-SWAP for OKX)
# Wait, ccxt_async.okx might just take standard CCXT unified symbols (SOL/USDT:USDT)
# Actually, CCXT standardizes swap symbols as BASE/QUOTE:SETTLE. For OKX swap, it is ALSO BASE/USDT:USDT in ccxt unified format!
# Let's just change EXCHANGE_ID for now to bypass the crash.

with open(config_path, 'w') as f:
    json.dump(config, f, indent=4)

print("config.json patched")
