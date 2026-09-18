#!/bin/bash
BOTS=(8401 8402 8403 8404 8405 8406 8407 8409 8410)
for b in "${BOTS[@]}"; do
    echo "Starting $b..."
    cd /Users/l/project/$b
    bash run.sh
done

echo "Starting 8888..."
pids_8888=$(ps aux | grep "[a]pp.py" | grep 8888 | awk '{print $2}')
for pid in $pids_8888; do
    if [ ! -z "$pid" ]; then
        kill -9 $pid 2>/dev/null
    fi
done
cd /Users/l/project/8888
nohup python3 /Users/l/project/8888/app.py > /dev/null 2>&1 &
echo "Done!"
