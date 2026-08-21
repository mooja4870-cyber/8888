import sys

path = "/Users/l/project/8888/ver.md"
with open(path, "r") as f:
    content = f.read()

new_ver = """## v2.3.16
Date: 2026-08-06

### 변경 내용
* 대시보드의 각 개별 봇 카드 섹션에서 '총 잔고' 라인 바로 위에 '초기 자본' 항목 신규 삽입 표출 (사용자 요청)

### 수정 파일
* dashboard.html
* index.html
* ver.md

### 비고
* 초기 자본(seed) 값을 추출하여 총 잔고와 동일한 디자인 포맷으로 일괄 적용 완료

"""

content = content.replace("# Version History\n", "# Version History\n\n" + new_ver)

with open(path, "w") as f:
    f.write(content)
