import sys

path = "/Users/l/project/8888/ver.md"
with open(path, "r") as f:
    content = f.read()

new_ver = """## v2.3.14
Date: 2026-08-06

### 변경 내용
* 디스코드 알림 메시지에서 '승패 O/x : 왼쪽=과거 → 오른쪽=최신' 안내 문구 삭제

### 수정 파일
* discord_alert.py
* ver.md

### 비고
* 사용자 요청 사항

"""

content = content.replace("# Version History\n", "# Version History\n\n" + new_ver)

with open(path, "w") as f:
    f.write(content)
