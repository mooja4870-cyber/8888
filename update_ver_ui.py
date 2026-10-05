import datetime

ver_path = "/Users/l/project/8401/ver.md"
with open(ver_path, 'r') as f:
    content = f.read()

new_entry = f"""
## v1.2.6
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 대시보드 UI(`app.py`, `ui/settings_tab.py`)에 잔존해 있던 8410 봇 및 Binance 관련 텍스트를 8401(OKX) 맞춤형으로 텍스트 수정 적용 완료.

### 수정 파일
* app.py
* ui/settings_tab.py

### 비고
* UI 렌더링 검증 완료.
"""

content = content + "\n" + new_entry

with open(ver_path, 'w') as f:
    f.write(content)

import subprocess
subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'commit', '-m', 'fix: 8401 대시보드 UI 잔존 Binance/8410 텍스트 수정'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'tag', 'v1.2.6'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'push', 'origin', 'v1.2.6'], cwd='/Users/l/project/8401')
print("ver.md updated and git committed for v1.2.6.")
