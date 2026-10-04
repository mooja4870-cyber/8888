#!/bin/bash
for d in /Users/l/project/84*; do
    if [ -d "$d" ]; then
        echo "Deploying to $d..."
        cp /Users/l/project/8888/scratch_scanner.py "$d/core/scanner.py"
        cp /Users/l/project/8888/scratch_engine.py "$d/core/engine.py"
        cp /Users/l/project/8888/scratch_scanner_tab.py "$d/ui/scanner_tab.py"
        cp /Users/l/project/8888/scratch_app.py "$d/app.py"
        
        # Kill the old streamlit & bot to restart
        # We need to restart streamlit to pick up app.py changes
        # And we need to restart bot.py to start generating scan_results.json
        pid=$(pgrep -f "streamlit run app.py --server.port $(basename $d)")
        if [ -n "$pid" ]; then
            kill -9 $pid
            echo "Killed Streamlit $pid for $(basename $d)"
        fi
        
        bot_pid=$(cat "$d/bot.pid" 2>/dev/null)
        if [ -n "$bot_pid" ]; then
            kill -9 $bot_pid 2>/dev/null
            rm "$d/bot.pid" "$d/trader.lock" 2>/dev/null
            echo "Killed bot.py $bot_pid for $(basename $d)"
        fi
        
        # Start bot
        cd "$d"
        nohup python3 bot.py > bot_stdout.log 2>&1 &
        echo $! > bot.pid
        
        # Start app
        nohup python3 -m streamlit run app.py --server.port $(basename $d) > streamlit_server.log 2>&1 &
    fi
done
