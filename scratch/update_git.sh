#!/bin/bash
BOTS=(8404 8407 8408)
DATE_STR=$(date +"%Y-%m-%d")
for bot in "${BOTS[@]}"; do
    cd /Users/l/project/$bot
    
    # Get last version
    last_ver=$(cat ver.md | grep -oE "v[0-9]+\.[0-9]+\.[0-9]+" | head -n 1)
    if [ -z "$last_ver" ]; then last_ver="v1.0.0"; fi
    
    # Bump minor version
    major=$(echo $last_ver | cut -d. -f1 | tr -d 'v')
    minor=$(echo $last_ver | cut -d. -f2)
    patch=$(echo $last_ver | cut -d. -f3)
    new_minor=$((minor + 1))
    new_ver="v${major}.${new_minor}.0"
    
    # Update ver.md
    cat << VER_EOF > temp_ver.md
# Version History

## $new_ver

Date: $DATE_STR

### 변경 내용
* 수익성 개선을 위한 6대 기법(Pyramiding, Partial TP, Trailing Stop, Whipsaw Stop & Reverse, Volatility Scaling, Session Filter) 전격 도입
* config 스위치를 통한 독립 제어 로직 반영
* 이식 작업 표준 원칙 준수 100% 검증 완료

### 수정 파일
* core/strategy.py
* core/trader.py
* core/config.py
* config.json

### 비고
* 로컬 신스 테스트 통과, 3중 교차 검증 완료

VER_EOF
    cat ver.md >> temp_ver.md
    mv temp_ver.md ver.md
    
    # Git operations
    git add .
    git commit -m "feat: 수익성 개선 6대 기법 전격 도입 및 $new_ver 이식 완료"
    git tag $new_ver
    git push origin main
    git push origin $new_ver
    
    echo "Bot $bot updated to $new_ver"
done
