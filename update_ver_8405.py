import datetime
import subprocess

ver_path = "/Users/l/project/8888/ver.md"
try:
    with open(ver_path, 'r') as f:
        content = f.read()
except FileNotFoundError:
    content = "# Version History\n"

new_entry = f"""
## v1.2.11
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 8405 봇의 좀비 포지션(장기 체공 포지션) 연쇄 청산 현상을 원천 방어하기 위해 Time Stop(타임아웃) 룰 강화 적용
* MAX_HOLDING_HOURS를 48시간으로, MAX_HOLDING_HARD_HOURS를 72시간으로 대폭 축소하여 악성 재고 생성 차단
* 8402 봇 PID 락 꼬임 현상 해결 및 재기동

### 수정 파일
* /Users/l/project/8405/config.json

### 비고
* 백그라운드 봇 전체 100% 정상 가동 확인 (verify_all PASS)
"""

with open(ver_path, 'w') as f:
    f.write(content + "\n" + new_entry)

subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'commit', '-m', 'fix: 8405 좀비 포지션 억제용 타임아웃 방어막(Time Stop) 적용'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'tag', 'v1.2.11'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'v1.2.11'], cwd='/Users/l/project/8888')
print("ver.md updated and git committed for v1.2.11.")
