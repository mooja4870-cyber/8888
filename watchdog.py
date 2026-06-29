#!/usr/bin/env python3
"""
8402 / 8403 봇 앱 자동복구 watchdog (mooja 승인 2026-06-25).

매 60초 TCP 포트를 점검해 죽은 봇만 재실행한다.
  - 살아있는 봇은 절대 건드리지/죽이지 않는다 (down일 때만 기동, 기동 전용).
  - 8888 폴더에서만 동작하며 다른 폴더의 소스는 일절 수정하지 않는다.
  - 각 봇은 자체 venv python으로 해당 폴더(cwd)에서 분리(start_new_session) 실행
    → watchdog 종료와 무관하게 생존.
"""
import os
import socket
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CHECK_INTERVAL = 60           # 1분 점검 주기
WARMUP_AFTER_LAUNCH = 18      # 기동 후 포트 바인딩 대기(중복 기동 방지 확인)
_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)   # /Users/l/project
LOG_FILE = os.path.join(_DIR, "watchdog.log")
LOG_DIR = os.path.join(_DIR, "watchdog_logs")


def _venv_py(folder):
    """봇 자체 venv python(없으면 시스템 python 폴백)."""
    p = os.path.join(_ROOT, folder, "venv", "bin", "python")
    return p if os.path.exists(p) else sys.executable


# (포트, cwd, python, argv)  — 8402·8403만 감시
TARGETS = [
    (8402, os.path.join(_ROOT, "8402"), _venv_py("8402"),
     ["-m", "streamlit", "run", "app.py", "--server.port", "8402", "--server.headless", "true"]),
    (8403, os.path.join(_ROOT, "8403"), _venv_py("8403"),
     ["-m", "streamlit", "run", "app.py", "--server.port", "8403", "--server.headless", "true"]),
]


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def log(msg):
    line = f"[{now()}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def port_alive(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def launch(port, cwd, py, argv):
    """해당 폴더에서 봇 venv python으로 분리 실행. 출력은 watchdog_logs/<port>.log."""
    os.makedirs(LOG_DIR, exist_ok=True)
    out = open(os.path.join(LOG_DIR, f"{port}.log"), "a", encoding="utf-8")
    out.write(f"\n===== [{now()}] watchdog 재실행: port {port} =====\n")
    out.flush()
    subprocess.Popen([py] + argv, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)


def main():
    log(f"watchdog 시작 — 대상 {[t[0] for t in TARGETS]}, 주기 {CHECK_INTERVAL}s (기동 전용, 종료 안 함)")
    while True:
        for port, cwd, py, argv in TARGETS:
            if port_alive(port):
                continue
            log(f"❌ {port} DOWN 감지 → 즉시 재실행 ({cwd})")
            try:
                launch(port, cwd, py, argv)
            except Exception as e:
                log(f"⚠️ {port} 재실행 실패: {str(e)[:150]}")
                continue
            time.sleep(WARMUP_AFTER_LAUNCH)
            log(f"{'✅' if port_alive(port) else '⏳'} {port} 재실행 후: "
                f"{'UP' if port_alive(port) else '기동 중(다음 주기 재확인)'}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
