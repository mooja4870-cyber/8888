import re
path = '/Users/l/project/8888/send_discord_stats.py'
with open(path, 'r', encoding='utf-8') as f:
    code = f.read()
code = code.replace('("8404", "8404_OKX"),', '("8403", "8403_OKX"),\n    ("8404", "8404_OKX"),\n    ("8405", "8405_OKX"),')
code = code.replace('[그룹3 (8404, 8406) 봇별 4개 구간 승패 상세]', '[그룹3 (8403, 8404, 8405, 8406) 봇별 4개 구간 승패 상세]')
code = code.replace('[그룹3 (8403, 8404, 8405, 8406) 봇별 4개 구간 승패 상세]', '[그룹3 (8403, 8404, 8405, 8406) 봇별 4개 구간 승패 상세]')
with open(path, 'w', encoding='utf-8') as f:
    f.write(code)
print("Stats patched.")
