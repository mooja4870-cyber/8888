with open("/Users/l/project/8888/discord_alert.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace('new_b["days"] = diff if diff > 0.01 else 0.01', 'new_b["days"] = diff if diff > 1.0 else 1.0')

with open("/Users/l/project/8888/discord_alert.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Patch 4 applied.")
