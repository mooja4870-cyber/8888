with open("/Users/l/project/8888/discord_alert.py", "r") as f:
    content = f.read()

content = content.replace("embeds.append({", "import requests\\n                embeds.append({")

with open("/Users/l/project/8888/discord_alert.py", "w") as f:
    f.write(content)
