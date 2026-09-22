#!/bin/bash
BOTS=(8401 8402 8403 8405 8407 8409 8410)
for b in "${BOTS[@]}"; do
    echo "Starting Streamlit for $b..."
    cd /Users/l/project/$b
    nohup python3 -m streamlit run app.py --server.port $b --server.headless true > /dev/null 2>&1 &
done
