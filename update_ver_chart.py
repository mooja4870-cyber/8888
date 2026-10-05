import datetime
import subprocess

ver_path = "/Users/l/project/8888/ver.md"
try:
    with open(ver_path, 'r') as f:
        content = f.read()
except FileNotFoundError:
    content = "# Version History\n"

new_entry = f"""
## v1.2.9
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 대시보드(app.py) 실자산 추이 렌더링 시 과거 데이터 표시 기간을 최대 7일로 제한하던 로직(`start_epoch` 필터) 삭제. 모든 봇이 초기화 이후부터 현재까지의 100% 전체 히스토리를 차트에 표출하도록 개선.

### 수정 파일
* app.py

### 비고
* UI 정상 렌더링 및 7일 이상 과거 데이터 정상 로드 확인 
"""

with open(ver_path, 'w') as f:
    f.write(content + "\n" + new_entry)

subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'commit', '-m', 'fix: 차트 히스토리 7일 표출 제한 해제 (초기화 시점부터 전체 렌더링)'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'tag', 'v1.2.9'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'v1.2.9'], cwd='/Users/l/project/8888')
print("ver.md updated and git committed for v1.2.9.")
