#!/bin/bash
for bot in 8401 8402 8403 8404 8405 8407 8408 8409 8410; do
    if [ -d "/Users/l/project/$bot" ]; then
        cd "/Users/l/project/$bot"
        
        # update ver.md
        if [ -f "ver.md" ]; then
            VERSION=$(grep -E "^## v" ver.md | head -n 1 | awk '{print $2}')
            # increment patch
            MAJOR=$(echo $VERSION | cut -d. -f1)
            MINOR=$(echo $VERSION | cut -d. -f2)
            PATCH=$(echo $VERSION | cut -d. -f3)
            NEW_PATCH=$((PATCH + 1))
            NEW_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
            
            DATE_STR=$(date "+%Y-%m-%d")
            
            # create new ver.md content
            cat << INNER_EOF > ver.md.new
# Version History

## $NEW_VERSION

Date: $DATE_STR

### 변경 내용
* 오프라인 청산 시 과거 체결 내역 오매칭 방지 로직 추가 (unlogged_exits 30분 제한)
* 연속 손절 로직 개선

### 수정 파일
* core/engine.py

INNER_EOF
            tail -n +2 ver.md >> ver.md.new
            mv ver.md.new ver.md
            
            git add core/engine.py ver.md
            git commit -m "fix: 오프라인 청산 시 과거 체결 내역이 합산되어 PnL 부호가 엇갈리는 버그 수정 (Time Window 30분 적용)"
            git tag $NEW_VERSION
            git push origin main
            git push origin $NEW_VERSION
            echo "Committed $bot with $NEW_VERSION"
        else
            git add core/engine.py
            git commit -m "fix: 오프라인 청산 과거 체결 내역 버그 수정"
            echo "Committed $bot without ver.md"
        fi
    fi
done
