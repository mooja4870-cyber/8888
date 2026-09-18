#!/bin/bash

echo "Cleaning up __pycache__ across all bots to prevent stale UI cache..."
find /Users/l/project/84[0-9]* -name "__pycache__" -type d -exec rm -rf {} +

# Find all bot directories (8400-8499) dynamically
bots=($(ls -d /Users/l/project/84[0-9]* 2>/dev/null | grep -E '/84[0-9]{2}$' | awk -F/ '{print $NF}'))


for b in "${bots[@]}"; do
    echo "Restarting UI for $b..."
    # Find all PIDs running the streamlit server for this bot
    pids=$(ps aux | grep "[a]pp.py --server.port $b" | awk '{print $2}')
    for pid in $pids; do
        if [ ! -z "$pid" ]; then
            kill -9 $pid 2>/dev/null
        fi
    done
    cd /Users/l/project/$b
    nohup /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python -m streamlit run app.py --server.port $b --server.headless true > /dev/null 2>&1 &
done

echo "Restarting 8888 central dashboard..."
pids_8888=$(ps aux | grep "[a]pp.py" | grep 8888 | awk '{print $2}')
for pid in $pids_8888; do
    if [ ! -z "$pid" ]; then
        kill -9 $pid 2>/dev/null
    fi
done
cd /Users/l/project/8888
nohup /opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python /Users/l/project/8888/app.py > /dev/null 2>&1 &

echo "All UIs and 8888 dashboard restarted successfully without cache!"
