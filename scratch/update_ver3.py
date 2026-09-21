import sys
import datetime

ver_file = "/Users/l/project/8888/ver.md"
with open(ver_file, "r") as f:
    content = f.read()

new_ver = f"""## v13.0.8

Date: {datetime.datetime.now().strftime('%Y-%m-%d')}

### 변경 내용
* 8404 봇을 통합 관제(대시보드) 및 디스코드 알림 집계 대상에서 제외
  * `BOTS` 리스트에서 제거, `EXCLUDED_BOTS` 에 추가

### 수정 파일
* app.py

### 비고
* 대시보드 리스타트 완료
* 8개 봇 점검 결과 보고와 함께 처리됨

"""

content = content.replace("# Version History\n\n", "# Version History\n\n" + new_ver)

with open(ver_file, "w") as f:
    f.write(content)
