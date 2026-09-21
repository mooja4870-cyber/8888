#!/bin/bash
for bot in 8401 8402 8403 8404 8405 8407 8408 8409 8410; do
    if [ -d "/Users/l/project/$bot" ]; then
        cd "/Users/l/project/$bot"
        
        if [ -f "ver.md" ]; then
            VERSION=$(grep -E "^## v" ver.md | head -n 1 | awk '{print $2}')
            MAJOR=$(echo $VERSION | cut -d. -f1)
            MINOR=$(echo $VERSION | cut -d. -f2)
            PATCH=$(echo $VERSION | cut -d. -f3)
            NEW_PATCH=$((PATCH + 1))
            NEW_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
            
            DATE_STR=$(date "+%Y-%m-%d")
            
            cat << INNER_EOF > ver.md.new
# Version History

## $NEW_VERSION

Date: $DATE_STR

### 변경 내용
* PnL 엇갈림 FoolProof 방어 로직 추가 (오염된 거래소 내역 무시하고 로컬 수익 채택)

### 수정 파일
* core/engine.py

INNER_EOF
            tail -n +2 ver.md >> ver.md.new
            mv ver.md.new ver.md
            
            git add core/engine.py ver.md
            git commit -m "feat: Foolproof 엇갈림 검증 로직 추가 (로컬 계산값 우선 채택)"
            git tag $NEW_VERSION
            git push origin main
            git push origin $NEW_VERSION
            echo "Committed $bot with $NEW_VERSION"
        fi
    fi
done
