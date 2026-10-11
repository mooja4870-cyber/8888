import os
filepath = '/Users/l/project/8888/ver.md'
with open(filepath, 'r') as f:
    content = f.read()

new_entry = """

## v1.2.17
Date: 2026-10-07

### 변경 내용
* [8402] 1일봉(1d) 추세추종 봇의 수학적 모순 해결을 위해 분할익절 완전 폐지 (USE_SCALEOUT: false)
* [8402] 손익비 극대화(RR 3.3)를 위해 익절 5.0 ATR, 손절 1.5 ATR로 재설정

### 수정 파일
* /Users/l/project/8402/config.json

### 비고
* 8402 봇 설정 변경 완료 및 디스코드 요약 알림 반영
"""

new_content = content.replace("# Version History", "# Version History" + new_entry)
with open(filepath, 'w') as f:
    f.write(new_content)

print("Updated 8888 ver.md")
