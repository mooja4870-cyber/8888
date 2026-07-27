import sys

with open("/Users/l/project/8888/ver.md", "r") as f:
    content = f.read()

new_ver = """
## v2.2.21
Date: 2026-07-27

### 변경 내용
* 8401 봇 스캐너 UI 진행도 표기 개선:
  1. 진입 조건이 통짜 (n/6)으로 표현되어 6개를 모두 만족해야 하는 것으로 오해할 수 있는 문제 해결
  2. A전략(눌림목: 4개 조건)과 B전략(밴드반등: 2개 조건)을 명확히 분리하여 `[A] n/4 | [B] n/2` 형태로 표시되도록 UI 개편
  3. UI 상단의 범례(Legend) 텍스트를 A, B 전략별로 분리 설명하도록 업데이트 완료

### 수정 파일
* `8401/ui/scanner_tab.py`
* `8888/ver.md`

### 비고
* UI 정상 렌더링 확인

"""

content = content.replace("# 버전 이력 (ver.md)\n", "# 버전 이력 (ver.md)\n" + new_ver)

with open("/Users/l/project/8888/ver.md", "w") as f:
    f.write(content)
