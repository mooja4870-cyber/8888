#!/bin/bash
bots=("8401" "8402" "8403" "8404" "8405" "8407" "8408" "8409")
DATE_STR="2026-07-28"

for b in "${bots[@]}"; do
    cd /Users/l/project/$b
    
    current_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "v1.0.0")
    IFS='.' read -ra ADDR <<< "${current_tag//v/}"
    major=${ADDR[0]:-1}
    minor=${ADDR[1]:-0}
    patch=${ADDR[2]:-0}
    new_patch=$((patch + 1))
    new_tag="v${major}.${minor}.${new_patch}"
    
    if [ -f "ver.md" ]; then
        sed -i '' "3i\\
## ${new_tag}\\
Date: ${DATE_STR}\\
\\
### 변경 내용\\
* 분할 청산 시 수익률(%) 표기 오류 수정 (전체 마진 기반 평균 수익률 산출)\\
* contractSize 오타 수정 (NameError 예방)\\
\\
### 수정 파일\\
* core/engine.py\\
* .golden/core/engine.py\\
\\
### 비고\\
* 디스코드/텔레그램 알림 PnL 정확도 개선\\
\\
" ver.md
    fi
    
    git add core/engine.py ver.md
    if [ -f ".golden/core/engine.py" ]; then
        git add .golden/core/engine.py 2>/dev/null || true
    fi
    
    git commit -m "fix: 분할 청산 시 수익률(%) 덮어쓰기 오류 수정 및 통합 마진 기반 수익률 재계산 적용"
    git tag $new_tag
    
    git push origin main 2>/dev/null || true
    git push origin $new_tag 2>/dev/null || true
    
    echo "Bot $b updated to $new_tag"
done
