#!/bin/bash
# ---------------------------------------------------------
# Watchdog Keeper (매 1분마다 크론에서 실행)
# ---------------------------------------------------------
# 목적: 9개 봇을 감시하는 중앙 워치독(watchdog_entry.py) 자체가
#       죽었을 경우 60초 이내에 강제 부활시킵니다.
# ---------------------------------------------------------

export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/opt/homebrew/sbin
BASE_DIR="/Users/l/project/8888"

# 1. watchdog_entry.py 확인
if ! pgrep -f "watchdog_entry.py" > /dev/null 2>&1; then
    echo "$(date '+%F %T') [KEEPER] 🚨 watchdog_entry.py 다운 감지! 재기동합니다..." >> "$BASE_DIR/watchdog_keeper.log"
    cd "$BASE_DIR" || exit
    nohup python3 "$BASE_DIR/watchdog_entry.py" >> "$BASE_DIR/watchdog_entry.log" 2>&1 &
fi

# 2. watchdog_position.py (진입 워치독) 확인
if ! pgrep -f "watchdog_position.py" > /dev/null 2>&1; then
    echo "$(date '+%F %T') [KEEPER] 🚨 watchdog_position.py 다운 감지! 재기동합니다..." >> "$BASE_DIR/watchdog_keeper.log"
    cd "$BASE_DIR" || exit
    nohup python3 "$BASE_DIR/watchdog_position.py" >> "$BASE_DIR/watchdog_position.log" 2>&1 &
fi

# 3. watchdog_exit.py (청산 워치독) 확인
if ! pgrep -f "watchdog_exit.py" > /dev/null 2>&1; then
    echo "$(date '+%F %T') [KEEPER] 🚨 watchdog_exit.py 다운 감지! 재기동합니다..." >> "$BASE_DIR/watchdog_keeper.log"
    cd "$BASE_DIR" || exit
    nohup python3 "$BASE_DIR/watchdog_exit.py" >> "$BASE_DIR/watchdog_exit.log" 2>&1 &
fi
