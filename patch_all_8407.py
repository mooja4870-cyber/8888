import re

# 1. Modify core/config.py
path = "/Users/l/project/8407/core/config.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace('EXCHANGE_ID: str = "okx"', 'EXCHANGE_ID: str = "binance"')
content = content.replace('BASE_URL: str = "https://www.okx.com"', 'BASE_URL: str = "https://fapi.binance.com"')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)


# 2. Modify app.py
path = "/Users/l/project/8407/app.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Just replace all occurrences of 8403 with 8407
content = content.replace("8403", "8407")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

# 3. Modify bot.py
path = "/Users/l/project/8407/bot.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("8403", "8407")
content = content.replace("okx", "binance") # Wait, 8403_okx -> 8407_binance

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

# 4. Modify .env
path_8403 = "/Users/l/project/8403/.env"
path_8407 = "/Users/l/project/8407/.env"

with open(path_8403, "r", encoding="utf-8") as f:
    env_8403 = f.readlines()

with open(path_8407, "r", encoding="utf-8") as f:
    env_8407 = f.readlines()

# Extract API Keys from 8407
keys = {}
for line in env_8407:
    if line.startswith("BINANCE_API_KEY="): keys["BINANCE_API_KEY"] = line.strip()
    if line.startswith("BINANCE_SECRET_KEY="): keys["BINANCE_SECRET_KEY"] = line.strip()
    if line.startswith("BINANCE_PASSPHRASE="): keys["BINANCE_PASSPHRASE"] = line.strip()

# Overwrite 8403's API keys with 8407's API keys (Binance)
new_env = []
for line in env_8403:
    if line.startswith("BINANCE_API_KEY="): new_env.append(keys.get("BINANCE_API_KEY", "BINANCE_API_KEY=\n") + "\n")
    elif line.startswith("BINANCE_SECRET_KEY="): new_env.append(keys.get("BINANCE_SECRET_KEY", "BINANCE_SECRET_KEY=\n") + "\n")
    elif line.startswith("BINANCE_PASSPHRASE="): new_env.append(keys.get("BINANCE_PASSPHRASE", "BINANCE_PASSPHRASE=\n") + "\n")
    # For OKX keys, just keep what 8403 had, it won't be used anyway
    else: new_env.append(line)

with open(path_8407, "w", encoding="utf-8") as f:
    f.writelines(new_env)

print("Done replacing hardcoded values and merging .env.")
