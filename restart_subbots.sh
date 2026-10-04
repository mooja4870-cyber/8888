#!/bin/bash
BOTS=("8403" "8404" "8405" "8408")
DATE=$(date "+%Y-%m-%d")

for bot in "${BOTS[@]}"; do
    cd /Users/l/project/$bot || continue
    
    python3 -m py_compile core/trader.py || { echo "Syntax error in $bot trader"; continue; }
    
    NEW_VER="v1.7.11-selfheal-sub"
    
    cat << INNER_EOF > temp_ver.md
# Version History

## $NEW_VER
Date: $DATE

### 변경 내용
* [$bot] Self-Healing (자가 치유) 3단계 방어망 전면 이식 (코어 봇과 통일)
* 비정상 무포지션 감지 및 Zombie Algo Order 클리너 

### 수정 파일
* core/trader.py

INNER_EOF

    cat temp_ver.md ver.md > ver.md.new && mv ver.md.new ver.md
    rm temp_ver.md
    
    git add ver.md core/trader.py
    git commit -m "feat: $bot Self-Healing 방어망 이식 (전 함대 면역 체계 통일)"
    git tag $NEW_VER
    
    echo "[$bot] Restarting..."
    bash run.sh > /dev/null 2>&1 &
done
echo "Subbots patched, committed, and restarted."
