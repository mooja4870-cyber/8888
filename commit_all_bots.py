import subprocess
import os

target_bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
msg = "fix: 스위칭 발동 최소 5건 제약 해제 (2건/3건일 때도 2패 시 스위칭)"

for b in target_bots:
    bot_path = f"/Users/l/project/{b}"
    
    # Check if there are changes
    res = subprocess.run(["git", "status", "--porcelain"], cwd=bot_path, capture_output=True, text=True)
    if res.stdout.strip():
        # Update ver.md
        ver_path = os.path.join(bot_path, "ver.md")
        if os.path.exists(ver_path):
            with open(ver_path, "r") as f:
                content = f.read()
            import datetime
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # Find the latest tag
            cmd = ["git", "describe", "--tags", "--abbrev=0"]
            tag_res = subprocess.run(cmd, cwd=bot_path, capture_output=True, text=True)
            if tag_res.returncode == 0 and tag_res.stdout.strip():
                latest_tag = tag_res.stdout.strip()
                # parse tag to increment patch
                if latest_tag.startswith("v"):
                    parts = latest_tag[1:].split(".")
                    if len(parts) == 3:
                        new_tag = f"v{parts[0]}.{parts[1]}.{int(parts[2])+1}"
                    else:
                        new_tag = "v1.0.0"
                else:
                    new_tag = "v1.0.0"
            else:
                new_tag = "v1.0.0"
            
            new_ver = f"""
## {new_tag}
Date: {today}

### 변경 내용
* 스위칭 모드(BlueFrog) 발동 제약 해제
  - 누적 거래 5건 미만(2건~4건) 상태에서도 2패 발생 시 즉각 스위칭 되도록 방어 로직 제거
  - 초기화 직후 빠른 연패 시 사각지대 해소

### 수정 파일
* `core/engine.py`

### 비고
* 전 봇 일괄 적용 패치
"""
            content = content.replace("# 버전 이력 (ver.md)\n", f"# 버전 이력 (ver.md)\n{new_ver}")
            with open(ver_path, "w") as f:
                f.write(content)
        
        # Git commit and push
        subprocess.run(["git", "add", "."], cwd=bot_path)
        subprocess.run(["git", "commit", "-m", msg], cwd=bot_path)
        if 'new_tag' in locals():
            subprocess.run(["git", "tag", new_tag], cwd=bot_path)
            subprocess.run(["git", "push", "origin", "main"], cwd=bot_path)
            subprocess.run(["git", "push", "origin", new_tag], cwd=bot_path)
            print(f"[{b}] Commited and pushed {new_tag}")
