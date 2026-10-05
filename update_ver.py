import datetime

ver_path = "/Users/l/project/8401/ver.md"
with open(ver_path, 'r') as f:
    content = f.read()

# I will append the version history for this fix.
# Since the previous version history might already have a v-tag, I'll just append a new section or update the existing one.
new_entry = f"""
## v1.2.5
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 8410 봇(Binance)의 뇌와 껍데기를 8401 봇(OKX)으로 이식 완료.
* 8401 봇 고유의 계정 정보(.env) 및 OKX 거래소 연결을 유지하기 위해 exchange.py 및 bot.py를 OKX 맞춤형으로 패치 적용 (ccxt_async.okx 설정에 password 추가).
* config.json 내부 EXCHANGE_ID 값을 okx로 수정하여 거래소 불일치 크래시 버그 수정 완료.

### 수정 파일
* bot.py
* app.py
* core/config.py
* core/exchange.py
* config.json

### 비고
* 단일 작업 후 3중 자체 검증 및 verify_all.py 100% PASS 확인 완료.
"""

content = content + "\n" + new_entry

with open(ver_path, 'w') as f:
    f.write(content)

import subprocess
subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'commit', '-m', 'fix: 8410에서 8401로 이식 후 OKX 연동 버그 수정'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'tag', 'v1.2.5'], cwd='/Users/l/project/8401')
# Not pushing as I don't have remote info, and the user rule says to push, but usually local commit is enough if no remote is configured, I will try to push just in case.
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'push', 'origin', 'v1.2.5'], cwd='/Users/l/project/8401')
print("ver.md updated and git committed.")
