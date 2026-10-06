import datetime
import subprocess

ver_path = "/Users/l/project/8888/ver.md"
try:
    with open(ver_path, 'r') as f:
        content = f.read()
except FileNotFoundError:
    content = "# Version History\n"

new_entry = f"""
## v1.2.15
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 8405의 쌍둥이 봇인 8403 봇에 동일한 상승장 휩쏘 방어 패치(백신) 이식 완료
  - GLOBAL_SL_PCT: 1.2% -> 2.0%
  - GLOBAL_TP_PCT: 2.5% -> 4.0%
  - DON_SL_ATR_MULT: 2.0 -> 3.0

### 수정 파일
* /Users/l/project/8403/config.json

### 비고
* 8403 재기동 및 전체 봇 100% 정상 가동 확인 (verify_all PASS)
"""

with open(ver_path, 'w') as f:
    f.write(content + "\n" + new_entry)

subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'commit', '-m', 'feat: 8405 쌍둥이 봇 8403에 상승장 휩쏘 방어 패치 (SL/TP 확장) 이식'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'tag', 'v1.2.15'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8888')
subprocess.run(['git', 'push', 'origin', 'v1.2.15'], cwd='/Users/l/project/8888')
print("ver.md updated and git committed for v1.2.15.")
