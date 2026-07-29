#!/bin/bash
bots=("8401" "8402" "8403" "8404" "8405" "8407" "8408" "8409")
for b in "${bots[@]}"; do
    cd /Users/l/project/$b
    current_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "v1.0.0")
    git tag -f $current_tag
    git push -f origin $current_tag 2>/dev/null || true
done
