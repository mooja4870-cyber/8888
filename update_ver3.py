import sys

path = "/Users/l/project/8888/ver.md"
with open(path, "r") as f:
    content = f.read()

new_ver = """## v2.3.11
Date: 2026-08-05

### 변경 내용
* 대시보드 봇 필터(수익/손실) 분류 기준을 누적수익금에서 '일평균수익률(>0%, <0%)' 기준으로 변경

### 수정 파일
* dashboard.html
* index.html
* ver.md

### 비고
* 사용자의 추가 요청에 따라 필터 분류 기준 수정 적용 및 검증 완료

"""

content = content.replace("# Version History\n", "# Version History\n\n" + new_ver)

with open(path, "w") as f:
    f.write(content)
