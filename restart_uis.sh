#!/bin/bash
bots=("8401" "8402" "8403" "8404" "8405" "8407" "8408" "8409")
for b in "${bots[@]}"; do
    echo "Restarting UI for $b..."
    pid=$(ps aux | grep "[a]pp.py --server.port $b" | awk '{print $2}')
    if [ ! -z "$pid" ]; then
        kill -9 $pid
    fi
    cd /Users/l/project/$b
    nohup /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python -m streamlit run app.py --server.port $b --server.headless true > /dev/null 2>&1 &
done
echo "All UIs restarted."
