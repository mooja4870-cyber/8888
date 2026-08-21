#!/bin/bash
NEW_VERSION="v2.3.7"
DATE=$(date +%Y-%m-%d)
cat << 'INNER_EOF' > temp_ver.md
# Version History

## v2.3.7
Date: 2026-08-03

### 변경 내용
* 디스코드 알림 발송 그룹 일괄 재편성 (사용자 요청 반영)
  * 1그룹: 8402, 8404, 8405, 8407, 8409 (총 5개 봇)
  * 2그룹: 8401, 8403, 8408 (총 3개 봇)
* `discord_alert.py`, `send_discord_hourly_graph.py`, `send_discord_stats.py` 3개 모듈의 알림 그룹 및 리포트 파트 표기 일괄 반영

### 수정 파일
* /8888/discord_alert.py
* /8888/send_discord_hourly_graph.py
* /8888/send_discord_stats.py
* /8888/ver.md

### 비고
* 디스코드 스케줄러 1그룹/2그룹 재편성 완료 및 문법 검증 완료

INNER_EOF

tail -n +2 /Users/l/project/8888/ver.md >> temp_ver.md
mv temp_ver.md /Users/l/project/8888/ver.md
