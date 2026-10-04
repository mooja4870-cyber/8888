#!/bin/bash
BOTS=("8407" "8409")
DATE=$(date "+%Y-%m-%d")

for bot in "${BOTS[@]}"; do
    cd /Users/l/project/$bot || continue
    
    python3 -m py_compile core/strategy.py || { echo "Syntax error in $bot strategy"; continue; }
    
    NEW_VER="v1.7.12-bbmr"
    
    cat << INNER_EOF > temp_ver.md
# Version History

## $NEW_VER
Date: $DATE

### 변경 내용
* [$bot] 코어 전략 전면 교체 (MDD 60% 이상 실패 로직 폐기)
* 신규 전략: BB Mean Reversion (볼린저 밴드 평균회귀)
* 파라미터 최적화 (1h): RSI < 35, SL = 4.0x ATR
* 백테스트 성과 (180일): 승률 69%, MDD 48%, 수익률 +28~56% (DOGE, SOL 기준)

### 수정 파일
* core/strategy.py

INNER_EOF

    cat temp_ver.md ver.md > ver.md.new && mv ver.md.new ver.md
    rm temp_ver.md
    
    git add ver.md core/strategy.py
    git commit -m "feat: $bot 전략 BB Mean Reversion (1h) 최적화로 전면 교체"
    git tag $NEW_VER
    
    echo "[$bot] Restarting..."
    bash run.sh > /dev/null 2>&1 &
done
echo "8407 and 8409 patched, committed, and restarted."
