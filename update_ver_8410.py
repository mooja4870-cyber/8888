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
* 8410 봇(비트코인/이더리움 등 메이저 코인 1시간봉 전략)의 상승장 휩쏘 방어력 대폭 상향
* 1시간봉 기준 깊은 조정을 견디기 위한 동적 손절/익절(ATR) 버퍼 확장
  - ATR_SL_MULT: 1.5 -> 2.5
  - ATR_TP_MULT: 3.0 -> 5.0
  - DON_SL_ATR_MULT: 2.0 -> 3.0
* 8401, 8402 등 타 봇의 좀비 프로세스/락 충돌 일괄 정리 및 복구

### 수정 파일
* /Users/l/project/8410/config.json

### 비고
* 8410 및 전체 봇 재기동, 100% 정상 가동 확인 (verify_all PASS)
"""

with open(ver_path, 'w') as f:
    f.write(content + "\n" + new_entry)

subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'commit', '-m', 'feat: 8410 상승장 휩쏘 방어용 ATR 동적 손익절 버퍼 대폭 확장'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'tag', 'v1.2.13'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'v1.2.13'], cwd='/Users/l/project/8888')
print("ver.md updated and git committed for v1.2.13.")
