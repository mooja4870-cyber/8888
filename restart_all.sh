#!/bin/bash
for bot in 8404 8406 8408; do
    echo "▶ Restarting $bot ..."
    cd "/Users/l/project/$bot"
    ./run_bot.sh stop 2>/dev/null || pkill -f "$bot" || true
    sleep 1
    bash run.sh
done
echo "All restarted."
