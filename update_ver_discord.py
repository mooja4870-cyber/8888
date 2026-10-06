import datetime
import subprocess

ver_path = "/Users/l/project/8888/ver.md"
try:
    with open(ver_path, 'r') as f:
        content = f.read()
except FileNotFoundError:
    content = "# Version History\n"

new_entry = f"""
## v1.2.14
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 디스코드 알림 발송 그룹 편성 조정
  - 그룹 1: 8402, 8405, 8410
  - 그룹 2: 8401, 8403, 8404, 8408

### 수정 파일
* /Users/l/project/8888/discord_alert.py

### 비고
* 알림 그룹 분할 발송 로직 업데이트 완료
"""

with open(ver_path, 'w') as f:
    f.write(content + "\n" + new_entry)

subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'commit', '-m', 'feat: 디스코드 알림 그룹 편성 조정 (G1: 8402,5,10 / G2: 8401,3,4,8)'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'tag', 'v1.2.14'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'v1.2.14'], cwd='/Users/l/project/8888')
print("ver.md updated and git committed for v1.2.14.")
