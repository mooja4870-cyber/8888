import os, subprocess, datetime

base = "/Users/l/project"
bots = ["8888", "8401", "8402", "8404", "8406", "8407", "8408", "8409"]
now = datetime.datetime.now()
date_str = now.strftime("%Y-%m-%d %H:%M")

for bot in bots:
    p = os.path.join(base, bot)
    if not os.path.exists(p): continue
    
    # Check if there are changes
    status = subprocess.check_output("git status --porcelain", shell=True, cwd=p, text=True)
    if not status.strip(): continue
    
    # Update ver.md
    ver_md = os.path.join(p, "ver.md")
    if os.path.exists(ver_md):
        with open(ver_md, "r", encoding="utf-8") as f:
            ver_data = f.read()
            
        # find the latest version
        # usually starts with | v1.2.3 | or ## v1.2.3
        # For 8888, it's | v... |
        if bot == "8888":
            import re
            m = re.search(r'\|\s*(v[\d\.]+)\s*\|', ver_data)
            if m:
                old_v = m.group(1)
                parts = old_v.strip('v').split('.')
                new_v = f"v{parts[0]}.{parts[1]}.{int(parts[2])+1}"
                new_line = f"| {new_v} | {date_str} | 대시보드 봇 이름 표시를 무지개색(.rainbow-text) 및 거래소 접미사 없이 순수 흰색 텍스트(예: 8401)로 복구 (사용자 요청) |\n"
                # insert after header
                ver_data = ver_data.replace("|------|------|------|\n", "|------|------|------|\n" + new_line)
        else:
            # For 84xx, format is ## vX.Y.Z
            import re
            m = re.search(r'##\s*(v[\d\.]+)', ver_data)
            if m:
                old_v = m.group(1)
                parts = old_v.strip('v').split('.')
                new_v = f"v{parts[0]}.{parts[1]}.{int(parts[2])+1}"
                date_only = now.strftime("%Y-%m-%d")
                new_block = f"## {new_v}\n\nDate: {date_only}\n\n### 변경 내용\n* 봇 이름(로고) UI 렌더링에서 무지개 폰트 효과(.rainbow-text) 및 거래소 접미사(OKX/Binance) 제거, 순수 봇 번호(흰색)로 복구 (사용자 요청)\n\n### 수정 파일\n* app.py\n\n### 비고\n* UI 통일화 작업\n\n"
                ver_data = ver_data.replace("# Version History\n\n", "# Version History\n\n" + new_block)
                
        with open(ver_md, "w", encoding="utf-8") as f:
            f.write(ver_data)
            
    # git operations
    subprocess.call("git add .", shell=True, cwd=p)
    subprocess.call('git commit -m "style: 봇 이름 UI 무지개폰트/접미사 제거 및 흰색 텍스트로 원복"', shell=True, cwd=p)
    # tag
    if os.path.exists(ver_md):
        subprocess.call(f"git tag {new_v}", shell=True, cwd=p)
        subprocess.call("git push origin main", shell=True, cwd=p)
        subprocess.call(f"git push origin {new_v}", shell=True, cwd=p)
        print(f"Updated and committed {bot} to {new_v}")

