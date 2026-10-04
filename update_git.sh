#!/bin/bash
for d in /Users/l/project/84*; do
    if [ -d "$d" ]; then
        if [[ $(basename "$d") == *"backup"* ]]; then
            continue
        fi
        echo "Updating Git for $(basename $d)..."
        cd "$d"
        
        # update ver.md
        cat << 'VER' > ver.md
# Version History

## v1.7.15
Date: 2026-10-01

### 변경 내용
* 스캐너 탭(UI) 연동 방식 변경: 중복 백그라운드 스캔 제거 및 파일 동기화(scan_results.json)
* 각 봇의 기존 스캐너 아키텍처(WebSocket 등) 보존하면서 래핑 적용

### 수정 파일
* core/scanner.py
* core/engine.py
* ui/scanner_tab.py
* app.py
VER
        
        git add core/scanner.py core/engine.py ui/scanner_tab.py app.py ver.md
        git commit -m "fix: 스캐너 UI 중복 스캔 제거 및 파일 기반 연동 적용 (v1.7.15)"
        git tag -f v1.7.15
    fi
done
