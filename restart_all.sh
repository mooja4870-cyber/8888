#!/bin/bash
echo "Killing all bot.py and app.py..."
pkill -f "python3 bot.py"
pkill -f "streamlit run app.py"
sleep 2

for d in /Users/l/project/84*; do
    if [ -d "$d" ]; then
        if [[ $(basename "$d") == *"backup"* ]]; then
            continue
        fi
        echo "Restarting $(basename $d)..."
        rm -f "$d/bot.pid" "$d/trader.lock" "$d/.lock"
        
        cd "$d"
        nohup python3 bot.py > bot_stdout.log 2>&1 &
        echo $! > bot.pid
        
        nohup python3 -m streamlit run app.py --server.port $(basename $d) > streamlit_server.log 2>&1 &
    fi
done
