import sys
import app
import json

data = app.collect()
for b in data["bots"]:
    if b["name"] == "8401":
        print(json.dumps(b, indent=2, default=str))
