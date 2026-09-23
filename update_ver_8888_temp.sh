#!/bin/bash
NEW_VER="v13.2.0"
DATE=$(date +"%Y-%m-%d")

tmpfile=$(mktemp)
cat << INNER_EOF > "$tmpfile"
## $NEW_VER
Date: $DATE

### 변경 내용
* 디스코드 알림 발송 시 봇 그룹 3개 분할로 재편성
  - 그룹 1: 8401, 8402, 8410 (기존 유지)
  - 그룹 2: 8405, 8407
  - 그룹 3: 8403, 8404, 8406, 8408, 8409

### 수정 파일
* discord_alert.py
* send_discord_stats.py
* send_discord_hourly_graph.py

### 비고
* 사용자 요청에 따라 알림 그룹을 3개로 분할 처리 완료.

INNER_EOF

cat ver.md >> "$tmpfile"
mv "$tmpfile" ver.md

git add .
git commit -m "feat: 디스코드 알림 그룹 3개 분할 재편성"
git tag $NEW_VER
git push origin main
git push origin $NEW_VER
