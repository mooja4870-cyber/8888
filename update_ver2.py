import sys

path = "/Users/l/project/8888/ver.md"
with open(path, "r") as f:
    content = f.read()

new_ver = """## v2.3.10
Date: 2026-08-05

### 변경 내용
* 대시보드 봇 필터(아코디언) 옵션 수정 (실제 서비스 파일 반영)

### 수정 파일
* dashboard.html
* ver.md

### 비고
* index.html 외에 실제 렌더링 파일인 dashboard.html에 동일한 수익/손실 필터 적용 완료

"""

content = content.replace("# Version History\n", "# Version History\n\n" + new_ver)

with open(path, "w") as f:
    f.write(content)
