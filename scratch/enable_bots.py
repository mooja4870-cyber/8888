import json
import os

bots = [8401, 8407, 8409]
for b in bots:
    path = f"/Users/l/project/{b}/config.json"
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
        data["AUTO_TRADING"] = True
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
        print(f"Enabled AUTO_TRADING for {b}")
