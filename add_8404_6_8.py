import os
import re

# 1. Update send_discord_stats.py
path1 = '/Users/l/project/8888/send_discord_stats.py'
with open(path1, 'r') as f: code1 = f.read()

code1 = re.sub(
    r'GROUP_2_BOTS = \[\s*\("8403", "8403_OKX"\),\s*\("8405", "8405_OKX"\),\s*\("8407", "8407_BNC"\),\s*\("8409", "8409_BNC"\),\s*\]',
    'GROUP_2_BOTS = [\n    ("8403", "8403_OKX"),\n    ("8404", "8404_OKX"),\n    ("8405", "8405_OKX"),\n    ("8406", "8406_OKX"),\n    ("8407", "8407_BNC"),\n    ("8408", "8408_BNC"),\n    ("8409", "8409_BNC"),\n]',
    code1
)

code1 = code1.replace(
    '🤖 **[그룹2 (8403, 8405, 8406, 8407, 8409) 봇별 4개 구간 승패 상세]**',
    '🤖 **[그룹2 (8403, 8404, 8405, 8406, 8407, 8408, 8409) 봇별 4개 구간 승패 상세]**'
)
code1 = code1.replace(
    '🤖 **[그룹2 (8403, 8405, 8407, 8409) 봇별 4개 구간 승패 상세]**',
    '🤖 **[그룹2 (8403, 8404, 8405, 8406, 8407, 8408, 8409) 봇별 4개 구간 승패 상세]**'
)

with open(path1, 'w') as f: f.write(code1)

# 2. Update send_discord_hourly_graph.py
path2 = '/Users/l/project/8888/send_discord_hourly_graph.py'
with open(path2, 'r') as f: code2 = f.read()

code2 = code2.replace(
    'GROUP_2_IDS = ["8403", "8405", "8406", "8407", "8409"]',
    'GROUP_2_IDS = ["8403", "8404", "8405", "8406", "8407", "8408", "8409"]'
)
code2 = code2.replace(
    'GROUP_2_IDS = ["8403", "8405", "8407", "8409"]',
    'GROUP_2_IDS = ["8403", "8404", "8405", "8406", "8407", "8408", "8409"]'
)
with open(path2, 'w') as f: f.write(code2)

# 3. Check app.py for GROUP_2
path3 = '/Users/l/project/8888/app.py'
with open(path3, 'r') as f: code3 = f.read()
if 'GROUP_2_IDS' in code3 or 'GROUP_2_BOTS' in code3:
    print("Found GROUP_2 in app.py!")
else:
    print("No GROUP_2 in app.py")

