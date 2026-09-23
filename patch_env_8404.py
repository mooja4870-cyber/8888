import sys

file_path = "/Users/l/project/8404/bot.py"
with open(file_path, "r") as f:
    content = f.read()

old_block = """    api_key    = os.getenv("BINANCE_API_KEY", "")
    secret_key = os.getenv("BINANCE_SECRET_KEY", "")
    passphrase = os.getenv("BINANCE_PASSPHRASE", "")"""

new_block = """    if str(CFG.EXCHANGE_ID).lower() == "okx":
        api_key    = os.getenv("OKX_API_KEY", "")
        secret_key = os.getenv("OKX_SECRET_KEY", "")
        passphrase = os.getenv("OKX_PASSPHRASE", "")
    else:
        api_key    = os.getenv("BINANCE_API_KEY", "")
        secret_key = os.getenv("BINANCE_SECRET_KEY", "")
        passphrase = os.getenv("BINANCE_PASSPHRASE", "")"""

content = content.replace(old_block, new_block)

with open(file_path, "w") as f:
    f.write(content)

print("Patched env vars in bot.py")
