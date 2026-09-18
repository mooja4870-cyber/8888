import re

# 1. Patch app.py
app_path = '/Users/l/project/8888/app.py'
with open(app_path, 'r', encoding='utf-8') as f:
    app_code = f.read()

app_code = app_code.replace(
    '("8401", 8401, "OKX"),    ("8402", 8402, "OKX"),\n    ("8404", 8404, "OKX"),',
    '("8401", 8401, "OKX"),    ("8402", 8402, "OKX"),\n    ("8403", 8403, "OKX"),    ("8404", 8404, "OKX"),\n    ("8405", 8405, "OKX"),'
)
app_code = app_code.replace(
    '[2026-09-14] 집계 및 관제 대상 7개 봇 (8401, 8402, 8404, 8406, 8407, 8409, 8410 / 8403, 8405 제외)',
    '[2026-09-15] 집계 및 관제 대상 9개 봇 (8401, 8402, 8403, 8404, 8405, 8406, 8407, 8409, 8410)'
)
with open(app_path, 'w', encoding='utf-8') as f:
    f.write(app_code)

# 2. Patch discord_alert.py
da_path = '/Users/l/project/8888/discord_alert.py'
with open(da_path, 'r', encoding='utf-8') as f:
    da_code = f.read()

da_code = da_code.replace('group_3_names = {"8404", "8406"}', 'group_3_names = {"8403", "8404", "8405", "8406"}')
da_code = da_code.replace('그룹 3: 봇 8404, 8406', '그룹 3: 봇 8403, 8404, 8405, 8406')
with open(da_path, 'w', encoding='utf-8') as f:
    f.write(da_code)

# 3. Patch send_discord_hourly_graph.py
hr_path = '/Users/l/project/8888/send_discord_hourly_graph.py'
with open(hr_path, 'r', encoding='utf-8') as f:
    hr_code = f.read()
hr_code = hr_code.replace('GROUP_3_IDS = ["8404", "8406"]', 'GROUP_3_IDS = ["8403", "8404", "8405", "8406"]')
hr_code = hr_code.replace('ALL_BOT_IDS = ["8407", "8409", "8401", "8402", "8410", "8404", "8406"]', 'ALL_BOT_IDS = ["8407", "8409", "8401", "8402", "8410", "8403", "8404", "8405", "8406"]')
with open(hr_path, 'w', encoding='utf-8') as f:
    f.write(hr_code)

print("Patching complete.")
