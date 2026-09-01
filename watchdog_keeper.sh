#!/bin/bash
# ---------------------------------------------------------
# Watchdog Keeper (매 1분마다 크론에서 실행)
# ---------------------------------------------------------
# 목적: 9개 봇을 감시하는 중앙 워치독(watchdog_entry.py) 자체가
#       죽었을 경우 60초 이내에 강제 부활시킵니다.
# ---------------------------------------------------------

export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/opt/homebrew/sbin
BASE_DIR="/Users/l/project/8888"

# watchdog_entry.py 프로세스가 실행 중인지 확인
if ! pgrep -f "watchdog_entry.py" > /dev/null 2>&1; then
    echo "$(date '+%F %T') [KEEPER] 🚨 워치독 데몬 다운 감지! 즉시 재기동합니다..." >> "$BASE_DIR/watchdog_keeper.log"
    cd "$BASE_DIR" || exit
    # 백그라운드에서 워치독 재시작
    nohup python3 "$BASE_DIR/watchdog_entry.py" >> "$BASE_DIR/watchdog_entry.log" 2>&1 &
fi
