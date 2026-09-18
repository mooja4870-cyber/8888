import app
import discord_alert
import json

data = app.collect()
# Let's inspect data["bots"][0]["seq"]
print([(b["name"], b.get("seq")) for b in data["bots"]])

