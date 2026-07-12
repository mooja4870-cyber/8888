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
    new_line = f"| {new_v} | {date_str} | 대시보드의 매매기법 비교 테이블 구조 반전(Transpose) 및 시간대별 성과 히트맵 섹션 완전 삭제 (사용자 요청) |\n"
    ver_data = ver_data.replace("|------|------|------|\n", "|------|------|------|\n" + new_line)

with open(ver_md, "w", encoding="utf-8") as f:
    f.write(ver_data)

subprocess.call("git add dashboard.html ver.md", shell=True, cwd=p)
subprocess.call('git commit -m "feat: 대시보드 테이블 구조 반전 및 히트맵 UI 삭제"', shell=True, cwd=p)
subprocess.call(f"git tag {new_v}", shell=True, cwd=p)

print(f"Committed as {new_v}")
