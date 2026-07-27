#!/bin/bash
NEW_VER="v0.9.367"
DATE=$(date "+%Y-%m-%d")
TMP=$(mktemp)

cat << INNER_EOF > "$TMP"
# Version History

## $NEW_VER
Date: $DATE

### 변경 내용
* 봇 매매이력(app.py, discord_alert.py) 집계 시 수익 0인 무승부 건이 누락되던 버그 수정
* 무승부 건수를 W/L/D 형태로 카운트(since_d, today_d)하고 디스코드 O/x 추이 문자열에 '-' 기호로 표기하도록 개선
* 부동소수점 오차 방지를 위해 round(v, 4) 적용

### 수정 파일
* app.py
* discord_alert.py

### 비고
* 단독 테스트(scratch/test_discord.py)를 통해 W/L/D 카운트 및 O/x/- 문자열 렌더링 정상 검증 완료

INNER_EOF

tail -n +2 ver.md >> "$TMP"
mv "$TMP" ver.md
git add ver.md app.py discord_alert.py
git commit -m "fix: 무승부(수익 0) 건 디스코드 매핑 누락 버그 수정 및 표기 개선"
git tag "$NEW_VER"
git push origin main
git push origin "$NEW_VER"
