import app
import discord_alert
import json

data = app.collect()
msg1, info1 = discord_alert.tick(data)
print("discord_alert.tick executed.")
