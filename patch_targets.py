import os
import re

files = ["app.py", "discord_alert.py", "send_discord_hourly_graph.py", "send_discord_5min_charts.py"]

for f in files:
    if not os.path.exists(f):
        continue
    with open(f, 'r') as file:
        content = file.read()
    
    # In app.py BOTS = [...]
    content = re.sub(r'\(\"840[2348]\",\s*840[2348],\s*\"[A-Z]+\"\),\s*', '', content)
    
    # Lists like ["8401", "8403", "8404", "8407", "8409", "8410"]
    content = re.sub(r'\"840[2348]\",\s*', '', content)
    
    # Sets like {"8401", "8403", "8404", "8407", "8409", "8410"}
    content = re.sub(r'\"840[2348]\",\s*', '', content)
    
    # dicts like "8403": "8403",
    content = re.sub(r'\"840[2348]\":\s*\"840[2348]\",\s*', '', content)
    
    with open(f, 'w') as file:
        file.write(content)
print("Patched.")
