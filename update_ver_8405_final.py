import datetime
import subprocess

ver_path = "/Users/l/project/8888/ver.md"
try:
    with open(ver_path, 'r') as f:
        content = f.read()
except FileNotFoundError:
    content = "# Version History\n"

new_entry = f"""
## v1.2.12
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 오진으로 인해 축소했던 8405 봇의 타임아웃 룰(MAX_HOLDING_HOURS)을 원래 수치(480h/720h)로 완벽 롤백
* 상승장(BULL) 고변동성 휩쏘 구간에서 잦은 기계적 손절(SL) 방어를 위해 손익절 버퍼 대폭 확대
  - GLOBAL_SL_PCT: 1.2% -> 2.0%
  - GLOBAL_TP_PCT: 2.5% -> 4.0%
  - DON_SL_ATR_MULT: 2.0 -> 3.0

### 수정 파일
* /Users/l/project/8405/config.json

### 비고
* 8405 재기동 및 전체 봇 100% 정상 가동 확인 (verify_all PASS)
"""

with open(ver_path, 'w') as f:
    f.write(content + "\n" + new_entry)

subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'commit', '-m', 'fix: 8405 타임아웃 롤백 및 고변동성 장세 방어용 SL/TP 여유폭 확대'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'tag', 'v1.2.12'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'v1.2.12'], cwd='/Users/l/project/8888')
print("ver.md updated and git committed for v1.2.12.")
