import os, subprocess, datetime, re

p = "/Users/l/project/8888"
now = datetime.datetime.now()
date_str = now.strftime("%Y-%m-%d %H:%M")

ver_md = os.path.join(p, "ver.md")
with open(ver_md, "r", encoding="utf-8") as f:
    ver_data = f.read()

m = re.search(r'\|\s*(v[\d\.]+)\s*\|', ver_data)
if m:
    old_v = m.group(1)
    parts = old_v.strip('v').split('.')
    new_v = f"v{parts[0]}.{parts[1]}.{int(parts[2])+1}"
    new_line = f"| {new_v} | {date_str} | 디스코드 알림 메시지 포맷 수정: 🔴, 🔵 등 모든 원형(원) 아이콘 제거 (사용자 요청) |\n"
    ver_data = ver_data.replace("|------|------|------|\n", "|------|------|------|\n" + new_line)

with open(ver_md, "w", encoding="utf-8") as f:
    f.write(ver_data)

subprocess.call("git add discord_alert.py ver.md", shell=True, cwd=p)
subprocess.call('git commit -m "feat: 디스코드 알림 🔴, 🔵 등 원형 아이콘 일괄 제거"', shell=True, cwd=p)
subprocess.call(f"git tag {new_v}", shell=True, cwd=p)
subprocess.call("git push origin main", shell=True, cwd=p)
subprocess.call(f"git push origin {new_v}", shell=True, cwd=p)

print(f"Committed as {new_v}")
