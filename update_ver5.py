import sys

path = "/Users/l/project/8888/ver.md"
with open(path, "r") as f:
    content = f.read()

new_ver = """## v2.3.13
Date: 2026-08-05

### 변경 내용
* 매매기법 비교 표의 '초기화 잔고' 값이 툴팁 수치와 동일하게 표시되도록 처리 정교화 (null/undefined 시 '$0.00'이 아닌 '—'로 출력)

### 수정 파일
* dashboard.html
* index.html
* ver.md

### 비고
* 사용자 피드백 반영

"""

content = content.replace("# Version History\n", "# Version History\n\n" + new_ver)

with open(path, "w") as f:
    f.write(content)
