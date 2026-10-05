import datetime
import subprocess

ver_path = "/Users/l/project/8888/ver.md"
try:
    with open(ver_path, 'r') as f:
        content = f.read()
except FileNotFoundError:
    content = "# Version History\n"

new_entry = f"""
## v1.2.8
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 대시보드(dashboard.html) 하단의 '봇별 총자산 추이' 탭 목록 배열에 누락되어 있던 8403 봇 추가 완료

### 수정 파일
* dashboard.html

### 비고
* UI 정상 렌더링 확인 
"""

with open(ver_path, 'w') as f:
    f.write(content + "\n" + new_entry)

subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'commit', '-m', 'fix: 대시보드 봇별 총자산 추이 탭에 8403 추가'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'tag', 'v1.2.8'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'v1.2.8'], cwd='/Users/l/project/8888')
print("ver.md updated and git committed for v1.2.8.")
