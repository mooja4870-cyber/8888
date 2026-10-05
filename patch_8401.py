import os

def replace_in_file(filepath, old, new):
    with open(filepath, 'r') as f:
        content = f.read()
    content = content.replace(old, new)
    with open(filepath, 'w') as f:
        f.write(content)

# Patch bot.py
bot_py = "/Users/l/project/8401/bot.py"
replace_in_file(bot_py, 'os.getenv("BINANCE_API_KEY", "")', 'os.getenv("OKX_API_KEY", "")')
replace_in_file(bot_py, 'os.getenv("BINANCE_SECRET_KEY", "")', 'os.getenv("OKX_SECRET_KEY", "")')
replace_in_file(bot_py, 'os.getenv("BINANCE_PASSPHRASE", "")', 'os.getenv("OKX_PASSPHRASE", "")')
replace_in_file(bot_py, '8410_binance', '8401_okx')

# Patch app.py
app_py = "/Users/l/project/8401/app.py"
replace_in_file(app_py, '8410_binance', '8401_okx')

# Patch core/config.py
config_py = "/Users/l/project/8401/core/config.py"
replace_in_file(config_py, '"binance"', '"okx"')
replace_in_file(config_py, '"https://fapi.binance.com"', '"https://www.okx.com"')

# Patch core/exchange.py
exch_py = "/Users/l/project/8401/core/exchange.py"
with open(exch_py, 'r') as f:
    exch = f.read()

# Replace ccxt init
old_init = """        self.exchange = ccxt_async.binance({
            "apiKey": api_key,
            "secret": secret_key,
            "options": {
                "defaultType": "future",
                "adjustForTimeDifference": True,
            },
            "enableRateLimit": True,
        })"""
new_init = """        self.exchange = ccxt_async.okx({
            "apiKey": api_key,
            "secret": secret_key,
            "password": passphrase,
            "options": {
                "defaultType": "swap",
                "adjustForTimeDifference": True,
            },
            "enableRateLimit": True,
        })"""
exch = exch.replace(old_init, new_init)
with open(exch_py, 'w') as f:
    f.write(exch)

print("Patch applied.")
