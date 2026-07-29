#!/bin/bash
bots=("8401" "8402" "8403" "8404" "8405" "8407" "8408" "8409")

for b in "${bots[@]}"; do
    cd /Users/l/project/$b
    
    # Git add ignoring untracked golden files if they cause errors
    git add app.py ver.md
    if [ -f ".golden/app.py" ]; then
        git add .golden/app.py 2>/dev/null || true
    fi
    
    git commit -m "fix: Streamlit UI 설정 실시간 동기화 패치 (캐시 지연 해소)"
    
    # Tag already created? Re-create it
    current_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "v1.0.0")
    git tag -f $current_tag
    
    # Push
    git push origin main 2>/dev/null || true
    git push -f origin $current_tag 2>/dev/null || true
    
    echo "Bot $b re-committed."
done
