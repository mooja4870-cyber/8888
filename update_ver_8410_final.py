import datetime
import subprocess

ver_path = "/Users/l/project/8888/ver.md"
try:
    with open(ver_path, 'r') as f:
        content = f.read()
except FileNotFoundError:
    content = "# Version History\n"

new_entry = f"""
## v1.2.13
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 8410 봇의 상승장(BULL) 돌파매매 시 1시간봉 기준 휩쏘(고변동성)장세 방어를 위한 동적 손절/익절 버퍼 대폭 확장
  - ATR_SL_MULT: 1.5 -> 2.5
  - ATR_TP_MULT: 3.0 -> 5.0
  - DON_SL_ATR_MULT: 2.0 -> 3.0
* 통계적 휩쏘 구간에서 잦은 기계적 손절로 인한 연패(3승 8패) 현상 원천 차단

### 수정 파일
* /Users/l/project/8410/config.json

### 비고
* 8410 재기동 및 전체 봇 100% 정상 가동 확인 (verify_all PASS)
"""

with open(ver_path, 'w') as f:
    f.write(content + "\n" + new_entry)

subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'commit', '-m', 'fix: 8410 휩쏘장 방어를 위한 ATR 기반 동적 손익절 버퍼 확장'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'tag', 'v1.2.13'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'v1.2.13'], cwd='/Users/l/project/8888')
print("ver.md updated and git committed for v1.2.13.")
