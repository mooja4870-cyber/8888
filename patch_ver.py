import sys

with open("/Users/l/project/8888/ver.md", "r") as f:
    content = f.read()

new_ver = """
## v2.2.20
Date: 2026-07-27

### 변경 내용
* 8401 봇 스캐너 직관성 향상:
  1. 진입 조건별 상태(추세, EMA정렬, 눌림/반등, RSI, BB이탈복귀, BB+RSI필터)를 스캐너 UI 대시보드에 개별적(✅/❌)으로 표시
  2. 전체 조건 충족 갯수 및 진행도 표기 (n/6)
  3. 로직 오염 방지(Checksum Guard)에 대응하여 .golden 디렉토리 내 코어 로직 백업 본 동시 반영
  4. 다중 실행된 백그라운드 엔진 좀비 프로세스 정리 완료 (StrategyEngine 오류 해결)

### 수정 파일
* `8401/core/strategy.py`
* `8401/.golden/core/strategy.py`
* `8401/core/scanner.py`
* `8401/ui/scanner_tab.py`
* `8888/ver.md`

### 비고
* UI 렌더링 및 백엔드 로그 에러 없는 상태 확인

"""

content = content.replace("# 버전 이력 (ver.md)\n", "# 버전 이력 (ver.md)\n" + new_ver)

with open("/Users/l/project/8888/ver.md", "w") as f:
    f.write(content)
