with open("/Users/l/project/8888/discord_alert.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace('new_b["since_w"] = last_w', 'new_b["since_w"] = wins')
content = content.replace('new_b["since_l"] = last_l', 'new_b["since_l"] = losses')

with open("/Users/l/project/8888/discord_alert.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Patch 3 applied.")
