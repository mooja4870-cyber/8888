#!/usr/bin/env python3
"""
8888 Position Exit & Protection Watchdog (`watchdog_exit.py`).
Delegates to shared `watchdog_common.run_log_watchdog` (<0.2% CPU, single-sink logging, flock restart lock).
"""
import os
import sys

BASE_8888 = os.path.dirname(os.path.abspath(__file__))
if BASE_8888 not in sys.path:
    sys.path.insert(0, BASE_8888)

from watchdog_common import run_log_watchdog

BOTS = ["8401", "8402", "8403", "8404", "8405", "8408"]
LOG_FILE = os.path.join(BASE_8888, "watchdog_exit.log")
DICT_PATH = os.path.join(BASE_8888, "error_dict.txt")

EXIT_ERROR_KEYWORDS = (
    "청산 실패",
    "청산 에러",
    "Failed to close",
    "Error closing",
    "청산 감지 오류",
    "청산 기록 점검 실패",
    "종료 실패",
    "exit error",
    "close position error",
)


def main():
    run_log_watchdog(
        role_name="watchdog_exit",
        banner="=== Position Exit Watchdog Started (V5 Low-CPU / Shared-Lock) ===",
        startup_notice="20초 주기 포지션 청산 점검 워치독 가동 (V5 Precompiled + Shared Lock)",
        heartbeat_notice="정기 감시 중 (전 봇 청산/보호주문 정상)",
        log_file=LOG_FILE,
        dict_path=DICT_PATH,
        bots=BOTS,
        fatal_keywords=(),
        static_keywords=EXIT_ERROR_KEYWORDS,
        alert_tag="EXIT V5",
        allow_fatal_pause=False,
        check_interval=20,
        silent_timeout=1800,
    )


if __name__ == "__main__":
    main()
