#!/usr/bin/env python3
"""
8888 Position Entry & Process Watchdog (`watchdog_position.py`).
Delegates to shared `watchdog_common.run_log_watchdog` (<0.2% CPU, single-sink logging, flock restart lock).
"""
import os
import sys

BASE_8888 = os.path.dirname(os.path.abspath(__file__))
if BASE_8888 not in sys.path:
    sys.path.insert(0, BASE_8888)

from watchdog_common import run_log_watchdog

BOTS = ["8401", "8402", "8403", "8404", "8405", "8408"]
LOG_FILE = os.path.join(BASE_8888, "watchdog_position.log")
DICT_PATH = os.path.join(BASE_8888, "error_dict.txt")

FATAL_KEYWORDS = ("InsufficientBalance", "Margin mode", "Position mode")
ERROR_KEYWORDS = (
    "NameError",
    "Exception",
    "Traceback",
    "Order failed",
    "진입 실패",
    "position error",
    "rate limit",
    "Too Many Requests",
    "조회 실패",
)


def main():
    run_log_watchdog(
        role_name="watchdog_position",
        banner="=== Position Entry Watchdog Started (V5 Low-CPU / Shared-Lock) ===",
        startup_notice="20초 주기 포지션 진입 점검 워치독 가동 (V5 Precompiled + Shared Lock)",
        heartbeat_notice="정기 감시 중 (전 봇 진입/프로세스 정상)",
        log_file=LOG_FILE,
        dict_path=DICT_PATH,
        bots=BOTS,
        fatal_keywords=FATAL_KEYWORDS,
        static_keywords=ERROR_KEYWORDS,
        alert_tag="POSITION V5",
        allow_fatal_pause=True,
        check_interval=20,
        silent_timeout=1800,
    )


if __name__ == "__main__":
    main()
