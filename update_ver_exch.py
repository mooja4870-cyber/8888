import datetime

ver_path = "/Users/l/project/8401/ver.md"
with open(ver_path, 'r') as f:
    content = f.read()

new_entry = f"""
## v1.2.7
Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 바이낸스 전용 API 파라미터(`fapiPrivateGetOpenAlgoOrders`, `positionSide`)를 OKX 규격(`fetch_open_orders`, `posSide`)으로 변환 패치 적용하여 주문 거절(Parameter posSide error 등) 문제 해결.

### 수정 파일
* core/exchange.py

### 비고
* 주문 생성 API 호출 성공(OKX 파라미터 오류 해결). 
"""

content = content + "\n" + new_entry

with open(ver_path, 'w') as f:
    f.write(content)

import subprocess
subprocess.run(['git', 'add', '.'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'commit', '-m', 'fix: OKX 전용 API 파라미터 변환 패치 (주문 거절 해결)'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'tag', 'v1.2.7'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'push', 'origin', 'main'], cwd='/Users/l/project/8401')
subprocess.run(['git', 'push', 'origin', 'v1.2.7'], cwd='/Users/l/project/8401')
print("ver.md updated and git committed for v1.2.7.")
