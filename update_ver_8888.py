import os
from datetime import datetime

base_dir = "/Users/l/project/8888"
today_str = datetime.now().strftime("%Y-%m-%d")
ver_path = os.path.join(base_dir, "ver.md")

with open(ver_path, "r", encoding="utf-8") as f:
    content = f.read()
    
# Find current version
import re
match = re.search(r'## v(\d+\.\d+\.\d+)', content)
if match:
    major, minor, patch = map(int, match.group(1).split('.'))
    new_patch = patch + 1
    new_version = f"v{major}.{minor}.{new_patch}"
    
    new_entry = f"""## {new_version}

Date: {today_str}

### 변경 내용
* 대시보드 새로고침 시 8개 봇이 잠시 노출되는 플리커링(Flickering) 방지
* `app.py`에서 `dashboard.html` 서빙 시 정적 placeholder 대신 실제 4개 봇의 상태(JSON)를 실시간 치환(Inject)하도록 개선

### 수정 파일
* app.py

### 비고
* 새로고침 시 체감 로딩 시간 0에 수렴

"""
    if "# Version History" in content:
        content = content.replace("# Version History", f"# Version History\n\n{new_entry}")
    else:
        content = f"{new_entry}\n{content}"
        
    with open(ver_path, "w", encoding="utf-8") as f:
        f.write(content)

    with open(os.path.join(base_dir, "commit.sh"), "w") as sf:
        sf.write(f'''#!/bin/bash
git add app.py ver.md
git commit -m "fix: 대시보드 새로고침 시 8개 봇이 순간 표시되는 플리커링 현상 해결"
git tag {new_version}
git push origin main
git push origin {new_version}
''')
        os.chmod(os.path.join(base_dir, "commit.sh"), 0o755)

print("ver.md updated and commit script created.")
