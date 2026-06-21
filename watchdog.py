#!/usr/bin/env python3
"""
8888 / 8408 / 8409 앱 감시(watchdog).

매 5분(300초) TCP 포트를 점검해 죽은 앱만 재실행한다.
  - 살아있는 앱은 절대 건드리지/죽이지 않는다 (down일 때만 기동).
  - 8888 폴더에서만 동작하며 다른 폴더의 소스는 일절 수정하지 않는다.
  - 각 앱은 해당 폴더(cwd)에서 분리(detached) 실행 → watchdog 종료와 무관하게 생존.

기동 명령(현재 실제 실행 방식과 동일):
  8888 : python app.py
  8408 : python -m streamlit run app.py --server.port 8408 --server.headless true
  8409 : python -m streamlit run app.py --server.port 8409 --server.headless true
"""
import os
import socket
import subprocess
import sys
import time

# Windows 콘솔 기본 코덱(cp949)이 이모지/em-dash를 못 찍어 죽는 것 방지
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CHECK_INTERVAL = 300          # 5분
WARMUP_AFTER_LAUNCH = 20      # 기동 후 포트 바인딩 대기(중복 기동 방지용 짧은 확인)
_DIR = os.path.dirname(os.path.abspath(__file__))
_DOWNLOADS = os.path.dirname(_DIR)   # C:\Users\노트북\Downloads
LOG_FILE = os.path.join(_DIR, "watchdog.log")
LOG_DIR = os.path.join(_DIR, "watchdog_logs")
PY = sys.executable           # 현재 watchdog을 띄운 동일 파이썬(Python312)

# (포트, cwd 폴더, 기동 인자[ PY 다음에 붙음 ])
TARGETS = [
    (8888, os.path.join(_DOWNLOADS, "8888"),
     ["app.py"]),
    (8401, os.path.join(_DOWNLOADS, "8401_okx"),
     ["-m", "streamlit", "run", "app.py", "--server.port", "8401", "--server.headless", "true"]),
    (8403, os.path.join(_DOWNLOADS, "8403_okx"),
     ["-m", "streamlit", "run", "app.py", "--server.port", "8403", "--server.headless", "true"]),
    (8405, os.path.join(_DOWNLOADS, "8405_okx"),
     ["-m", "streamlit", "run", "app.py", "--server.port", "8405", "--server.headless", "true"]),
    (8406, os.path.join(_DOWNLOADS, "8406_okx"),
     ["-m", "streamlit", "run", "app.py", "--server.port", "8406", "--server.headless", "true"]),
    (8408, os.path.join(_DOWNLOADS, "8408_bnc"),
     ["-m", "streamlit", "run", "app.py", "--server.port", "8408", "--server.headless", "true"]),
    (8409, os.path.join(_DOWNLOADS, "8409_bnc"),
     ["-m", "streamlit", "run", "app.py", "--server.port", "8409", "--server.headless", "true"]),
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


def launch(port, cwd, argv):
    """해당 폴더에서 앱을 분리 실행. 출력은 watchdog_logs/<port>.log 로."""
    os.makedirs(LOG_DIR, exist_ok=True)
    out_path = os.path.join(LOG_DIR, f"{port}.log")
    flags = 0
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP → watchdog과 독립 생존
        flags = 0x00000008 | 0x00000200
    out = open(out_path, "a", encoding="utf-8")
    out.write(f"\n===== [{now()}] watchdog 재실행: port {port} =====\n")
    out.flush()
    subprocess.Popen([PY] + argv, cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)


def main():
    log(f"watchdog 시작 — 대상 {[t[0] for t in TARGETS]}, 주기 {CHECK_INTERVAL}s")
    while True:
        for port, cwd, argv in TARGETS:
            if port_alive(port):
                continue
            log(f"❌ {port} DOWN 감지 → 재실행 ({cwd})")
            try:
                launch(port, cwd, argv)
            except Exception as e:
                log(f"⚠️ {port} 재실행 실패: {str(e)[:150]}")
                continue
            time.sleep(WARMUP_AFTER_LAUNCH)
            log(f"{'✅' if port_alive(port) else '⏳'} {port} 재실행 후 상태: "
                f"{'UP' if port_alive(port) else '아직 기동 중(다음 주기 재확인)'}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
