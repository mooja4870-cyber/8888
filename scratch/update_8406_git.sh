#!/bin/bash
bot=8406
DATE_STR=$(date +"%Y-%m-%d")
cd /Users/l/project/$bot

# Get last version
last_ver=$(cat ver.md | grep -oE "v[0-9]+\.[0-9]+\.[0-9]+" | head -n 1)
if [ -z "$last_ver" ]; then last_ver="v1.0.0"; fi

# Bump minor version
major=$(echo $last_ver | cut -d. -f1 | tr -d 'v')
minor=$(echo $last_ver | cut -d. -f2)
new_minor=$((minor + 1))
new_ver="v${major}.${new_minor}.0"

# Update ver.md
cat << VER_EOF > temp_ver.md
# Version History

## $new_ver

Date: $DATE_STR

### 변경 내용
* 8405 봇의 핵심 매매 로직, UI, 설정값 전격 이식 완료 (이식 작업 표준 원칙 준수)

### 수정 파일
* core/ 디렉터리 내 전체 로직 파일
* app.py
* bot.py
* config.json

### 비고
* 기존 계정 및 실행 포트 완벽 보존 3중 교차 검증 완료

VER_EOF
cat ver.md >> temp_ver.md
mv temp_ver.md ver.md

# Git operations
git add .
git commit -m "feat: 8405 봇 핵심 로직 및 UI 전격 이식 완료 ($new_ver)"
git tag $new_ver
git push origin main
git push origin $new_ver

echo "Bot $bot updated to $new_ver"
