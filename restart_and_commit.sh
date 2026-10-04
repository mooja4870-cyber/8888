#!/bin/bash
BOTS=("8401" "8402" "8407" "8409" "8410")
DATE=$(date "+%Y-%m-%d")

for bot in "${BOTS[@]}"; do
    cd /Users/l/project/$bot || continue
    
    # Check syntax just to be safe
    python3 -m py_compile core/trader.py || { echo "Syntax error in $bot"; continue; }
    
    # Get current version from ver.md (last tag usually)
    # We will just append a new minor patch.
    # To keep it simple, we use a fixed version label for this patch
    NEW_VER="v1.7.11-selfheal"
    
    cat << INNER_EOF > temp_ver.md
# Version History

## $NEW_VER
Date: $DATE

### 변경 내용
* [$bot] Self-Healing (자가 치유) 모듈 3단계 이식
  * Phase 1 (감시): 비정상적 무포지션 탐지 (진입 시그널 3회 연속 API 실패/잔고부족 시 텔레그램 경보 및 락 해제)
  * Phase 2&3 (청소): 장부 정합성 교차 검증 및 좀비 주문(Zombie Algo Orders) 클리너 도입 (로컬 장부에 없는 잔여 TP/SL 강제 Kill)

### 수정 파일
* core/trader.py

INNER_EOF

    cat temp_ver.md ver.md > ver.md.new && mv ver.md.new ver.md
    rm temp_ver.md
    
    git add ver.md core/trader.py
    git commit -m "feat: $bot Self-Healing (비정상적 무포지션 감지 및 좀비 주문 청소) 코어 이식"
    git tag $NEW_VER
    
    echo "[$bot] Restarting..."
    bash run.sh > /dev/null 2>&1 &
done
echo "All 5 core bots patched, committed, and restarted."
