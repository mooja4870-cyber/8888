import datetime
import subprocess

ver_path = "/Users/l/project/8888/ver.md"
try:
    with open(ver_path, 'r') as f:
        content = f.read()
except FileNotFoundError:
    content = "# Version History\n"

new_entry = f"""
## v1.2.16
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 디스코드 알림 발송 시 '최근 14일 봇별 매매전략 및 설정 변경 요약'을 파싱하여 발송하는 로직 추가
* 디스코드 알림 발송 순서를 1) 최근 변경 요약 -> 2) 그룹2 -> 3) 그룹1 로 변경

### 수정 파일
* /Users/l/project/8888/discord_alert.py
"""

with open(ver_path, 'w') as f:
    f.write(content + "\n" + new_entry)

subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'commit', '-m', 'feat: 최근 14일 봇별 설정 변경 요약 디스코드 발송 기능 추가 및 발송 순서 변경'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'tag', 'v1.2.16'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'v1.2.16'], cwd='/Users/l/project/8888')
print("ver.md updated and git committed for v1.2.16.")
