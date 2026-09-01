import json, os
for b in [8401,8402,8403,8404,8405,8407,8408,8409,8410]:
    with open(f"/Users/l/project/{b}/config.json", "r") as f:
        cfg = json.load(f)
        print(f"Bot {b} USE_BLUEFROG: {cfg.get('USE_BLUEFROG')}")
