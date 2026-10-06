import datetime
import subprocess

ver_path = "/Users/l/project/8888/ver.md"
try:
    with open(ver_path, 'r') as f:
        content = f.read()
except FileNotFoundError:
    content = "# Version History\n"

new_entry = f"""
## v1.2.10
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* watchdog_keeper.sh 스크립트를 개선하여 기존의 메인 감시망(watchdog_entry.py) 외에도 포지션 진입 워치독(watchdog_position.py)과 청산 워치독(watchdog_exit.py)까지 총 3개의 워치독 프로세스를 1분마다 전수 감시하고 자동 부활시키도록 로직 보강.
* 중단되어 있던 진입/청산 워치독 2개 백그라운드 강제 재기동 완료 (디스코드 알림 정상화).

### 수정 파일
* watchdog_keeper.sh

### 비고
* 진입/청산 3중 방어망 완전 복구 및 정상 작동 확인 완료
"""

with open(ver_path, 'w') as f:
    f.write(content + "\n" + new_entry)

subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'commit', '-m', 'fix: 3중 워치독 자동 부활 로직(Keeper) 보강 및 프로세스 재기동'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'tag', 'v1.2.10'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'v1.2.10'], cwd='/Users/l/project/8888')
print("ver.md updated and git committed for v1.2.10.")
