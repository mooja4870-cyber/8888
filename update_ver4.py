import sys

path = "/Users/l/project/8888/ver.md"
with open(path, "r") as f:
    content = f.read()

new_ver = """## v2.3.12
Date: 2026-08-05

### 변경 내용
* 대시보드 '매매기법 비교' 표에 봇 초기화 잔고($ 단위, 소수점 2자리) 컬럼 추가 (사용자 요청)

### 수정 파일
* dashboard.html
* index.html
* ver.md

### 비고
* '봇'과 '거래소' 컬럼 사이에 새롭게 추가 적용됨

"""

content = content.replace("# Version History\n", "# Version History\n\n" + new_ver)

with open(path, "w") as f:
    f.write(content)
