#!/bin/bash
# ---------------------------------------------------------
# Watchdog Keeper & Dead-Man's Switch (매 1분마다 크론에서 실행)
# ---------------------------------------------------------
# 1. 4대 워치독 + 8888 app.py 프로세스 생존 감시 및 부활
# 2. [M19 Dead-Man's Switch] PID가 살아있더라도 하트비트가 임계시간 초과
#    침묵 시 프리즈로 판단해 강제 종료·재기동 + Discord/Telegram CRITICAL 발송
# 3. [TTL 정비 락] /tmp/watchdog_maintenance.json 유효 시(최대 600s) M1 간섭 예방
# 4. [M24] keeper 로그 자체 로테이션(5MB 상한)
# ---------------------------------------------------------

export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/opt/homebrew/sbin
BASE_DIR="/Users/l/project/8888"
KEEPER_LOG="$BASE_DIR/watchdog_keeper.log"
MAINT_FILE="/tmp/watchdog_maintenance.json"
HB_FILE="$BASE_DIR/data/watchdog_heartbeat.json"

# 0. Self-rotate keeper log (>5MB) cleanly via copytruncate
if [ -f "$KEEPER_LOG" ]; then
    ksz=$(wc -c < "$KEEPER_LOG" 2>/dev/null || echo 0)
    if [ "$ksz" -gt 5242880 ]; then
        cp -f "$KEEPER_LOG" "$KEEPER_LOG.1" 2>/dev/null && : > "$KEEPER_LOG"
    fi
fi

# Check TTL maintenance window (auto-expires if past expires_ts)
ENTRY_MAINT=0
if [ -f "$MAINT_FILE" ]; then
    ENTRY_MAINT=$(python3 -c '
import json, os, time
p = "/tmp/watchdog_maintenance.json"
try:
    d = json.load(open(p))
    if float(d.get("expires_ts", 0)) > time.time():
        print(1)
    else:
        os.remove(p)
        print(0)
except Exception:
    try: os.remove(p)
    except Exception: pass
    print(0)
' 2>/dev/null || echo 0)
fi

check_and_heal_daemon() {
    local role="$1"
    local script="$2"
    local log_out="$3"
    local max_hb_age="$4"
    local skip_revive="${5:-0}"

    local pid
    pid=$(pgrep -f "$script" | head -n 1 || true)

    if [ -z "$pid" ]; then
        if [ "$skip_revive" = "1" ]; then
            echo "$(date '+%F %T') [KEEPER] 🛠️ 정비 윈도우 활성 — $script 부활 유예" >> "$KEEPER_LOG"
            return 0
        fi
        echo "$(date '+%F %T') [KEEPER] 🚨 $script 다운 감지! 재기동합니다..." >> "$KEEPER_LOG"
        cd "$BASE_DIR" || return 1
        nohup python3 "$BASE_DIR/$script" >> "$log_out" 2>&1 &
        return 0
    fi

    # Dead-Man's Switch: alive PID with frozen heartbeat (> max_hb_age AND process uptime > 150s)
    if [ -n "$max_hb_age" ] && [ "$max_hb_age" -gt 0 ] && [ -f "$HB_FILE" ]; then
        local frozen_msg
        frozen_msg=$(python3 -c '
import json, os, subprocess, sys, time
role, pid_s, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])
hb_file = sys.argv[4]
try:
    d = json.load(open(hb_file))
    rec = (d.get("heartbeats") or {}).get(role) or {}
    hb_ts = float(rec.get("ts") or 0.0)
    if hb_ts <= 0:
        sys.exit(0)
    # Check process elapsed time first so freshly started daemons are not killed before first heartbeat
    et = subprocess.check_output(["ps", "-p", pid_s, "-o", "etime="], text=True).strip()
    days = 0
    if "-" in et:
        dp, et = et.split("-", 1)
        days = int(dp) if dp.isdigit() else 0
    ps = [int(x) if x.isdigit() else 0 for x in et.split(":")]
    if len(ps) == 3:
        up = days*86400 + ps[0]*3600 + ps[1]*60 + ps[2]
    elif len(ps) == 2:
        up = days*86400 + ps[0]*60 + ps[1]
    else:
        up = days*86400 + (ps[0] if ps else 0)
    hb_age = time.time() - hb_ts
    if up > max(180, limit) and hb_age > limit:
        print(f"uptime={up}s hb_age={int(hb_age)}s>{limit}s")
except Exception:
    pass
' "$role" "$pid" "$max_hb_age" "$HB_FILE" 2>/dev/null || true)

        if [ -n "$frozen_msg" ]; then
            echo "$(date '+%F %T') [KEEPER] 🚨 [Dead-Man Switch] $script (PID $pid) 프리즈 감지($frozen_msg) — 강제 회수 후 부활" >> "$KEEPER_LOG"
            kill -TERM "$pid" 2>/dev/null || true
            sleep 2
            kill -KILL "$pid" 2>/dev/null || true
            cd "$BASE_DIR" || return 1
            nohup python3 "$BASE_DIR/$script" >> "$log_out" 2>&1 &
            python3 -c '
import sys
sys.path.insert(0, "/Users/l/project/8888")
from watchdog_common import _send_discord, _send_telegram
msg = f"🚨 **[Dead-Man Switch 발동 / {sys.argv[1]}]**\n워치독 프로세스(PID {sys.argv[2]}) 응답 침묵 감지({sys.argv[3]}) → 강제 회수 후 자동 부활 완료"
_send_discord(msg)
_send_telegram(msg)
' "$script" "$pid" "$frozen_msg" >/dev/null 2>&1 || true
        fi
    fi
}

# 1. watchdog_entry.py (M19 heartbeat 300s)
check_and_heal_daemon "watchdog_entry" "watchdog_entry.py" "$BASE_DIR/watchdog_entry.log" 300 "$ENTRY_MAINT"

# 2. watchdog_position.py (M19 heartbeat 180s)
check_and_heal_daemon "watchdog_position" "watchdog_position.py" "$BASE_DIR/watchdog_position.log" 180 0

# 3. watchdog_exit.py (M19 heartbeat 180s)
check_and_heal_daemon "watchdog_exit" "watchdog_exit.py" "$BASE_DIR/watchdog_exit.log" 180 0

# 4. 8888 통합 관제 대시보드 (app.py) 확인
if ! pgrep -f ".*8888/app.py" > /dev/null 2>&1; then
    echo "$(date '+%F %T') [KEEPER] 🚨 8888 app.py 다운 감지! 재기동합니다..." >> "$KEEPER_LOG"
    cd "$BASE_DIR" || exit
    nohup python3 "$BASE_DIR/app.py" >> "$BASE_DIR/app.log" 2>&1 &
    echo $! > "$BASE_DIR/app.pid"
fi

# 5. watchdog_profitability.py (M19 heartbeat 900s)
check_and_heal_daemon "watchdog_profitability" "watchdog_profitability.py" "$BASE_DIR/watchdog_profitability.log" 900 0
