#!/bin/bash
bots=("8401" "8402" "8403" "8404" "8405" "8407" "8408" "8409")
DATE_STR="2026-07-27"

for b in "${bots[@]}"; do
    cd /Users/l/project/$b
    
    # Get current tag
    current_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "v1.0.0")
    
    # Parse version parts
    IFS='.' read -ra ADDR <<< "${current_tag//v/}"
    major=${ADDR[0]:-1}
    minor=${ADDR[1]:-0}
    patch=${ADDR[2]:-0}
    
    # Increment patch for UI bug fix
    new_patch=$((patch + 1))
    new_tag="v${major}.${minor}.${new_patch}"
    
    # Update ver.md
    if [ -f "ver.md" ]; then
        sed -i '' "3i\\
## ${new_tag}\\
Date: ${DATE_STR}\\
\\
### 변경 내용\\
* Streamlit UI 설정 실시간 동기화 패치 추가 (백엔드 스위칭 시 즉각 화면 반영)\\
\\
### 수정 파일\\
* app.py\\
* .golden/app.py\\
\\
### 비고\\
* UI 캐시 지연 현상 완벽 해결\\
\\
" ver.md
    fi
    
    # Git commit & tag
    git add app.py .golden/app.py ver.md
    git commit -m "fix: Streamlit UI 설정 실시간 동기화 패치 (캐시 지연 해소)"
    git tag $new_tag
    
    # Push (ignoring failures for bots without origin)
    git push origin main 2>/dev/null || true
    git push origin $new_tag 2>/dev/null || true
    
    echo "Bot $b updated to $new_tag"
done
