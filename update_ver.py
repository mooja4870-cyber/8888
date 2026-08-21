import sys

path = "/Users/l/project/8888/ver.md"
with open(path, "r") as f:
    content = f.read()

new_ver = """## v2.3.9
Date: 2026-08-05

### 변경 내용
* 대시보드 봇 필터(아코디언) 옵션을 수익 봇, 손실 봇 기준으로 변경

### 수정 파일
* index.html
* ver.md

### 비고
* 그룹별 분리 제거 및 수익/손실 필터 적용 완료

"""

content = content.replace("# Version History\n", "# Version History\n\n" + new_ver)

with open(path, "w") as f:
    f.write(content)
