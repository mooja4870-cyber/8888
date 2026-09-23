#!/bin/bash
for bot in 8404 8406 8408; do
    echo "▶ Stopping $bot ..."
    pids=$(ps aux | grep -v grep | grep "$bot/bot.py" | awk '{print $2}')
    if [ ! -z "$pids" ]; then kill -9 $pids; fi
    pids=$(ps aux | grep -v grep | grep "$bot/app.py" | awk '{print $2}')
    if [ ! -z "$pids" ]; then kill -9 $pids; fi
done
sleep 1

for bot in 8404 8406 8408; do
    echo "▶ Starting $bot ..."
    cd "/Users/l/project/$bot"
    bash run.sh
done
echo "All restarted."
