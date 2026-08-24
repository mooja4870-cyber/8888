#!/usr/bin/env python3
"""
8888 앱 및 8개 봇 (app.py + bot.py) 자동복구 & 중복방지 watchdog (mooja 지시/승인).

매 5분(300초)마다 전체 타겟(8888 app.py 및 8401~8409의 app.py, bot.py 16개 쌍)을 점검:
  - 중복 실행(PID 2개 이상) 감지 시 중복 프로세스 정리 후 단일 정상 기동 보장.
  - DOWN 감지 시 즉시 해당 폴더(cwd) 및 venv python으로 분리(start_new_session) 기동.
  - 살아있는 단일 정상 프로세스는 절대 건드리지 않는다.
  - 8888 폴더에서만 동작하며 타 봇 폴더의 소스코드는 일절 수정하지 않는다.
"""
import os
import signal
import socket
import subprocess
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CHECK_INTERVAL = 300           # 5분(300초) 점검 주기
WARMUP_AFTER_LAUNCH = 15       # 기동 후 포트 바인딩 대기
_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)  # /Users/l/project
LOG_FILE = os.path.join(_DIR, "watchdog.log")
LOG_DIR = os.path.join(_DIR, "watchdog_logs")


def _venv_py(folder):
    """봇 자체 venv python(없으면 시스템 python 폴백)."""
    p = os.path.join(_ROOT, folder, "venv", "bin", "python")
    return p if os.path.exists(p) else sys.executable


# 감시 대상 구성: 8888 app + 테스트 4봇의 (app.py, bot.py)
#
# [2026-08-11] 4봇 테스트 체제로 축소. 종전 목록은 8402·8404·8405를 포함하고 8409는
# 빠져 있었다. 이 워치독은 DOWN을 감지하면 즉시 재기동하므로, 정지시킨 봇을 목록에
# 남겨두면 되살아난다(/Users/l/project/watchdog_all.sh 와 같은 문제).
# 테스트 종료 후 원복: ["8401","8402","8403","8404","8405","8408"]
# [2026-08-18 17:30] mooja 지시로 4봇 자동재기동 복구.
# 8403은 이동평균 20/100 일봉 전략으로 교체 완료.
# 8401(MFI)·8408·8409(이중볼린저)는 3년 백테스트에서 마이너스로 확인된 전략이지만
# [2026-08-24] 집계·알림 대상 6개 봇 (8401, 8402, 8403, 8404, 8408, 8409)
BOTS = ["8401", "8402", "8403", "8404", "8408", "8409"]

def build_targets():
    targets = []
    # 1. 8888 통합 관제 대시보드
    targets.append({
        "name": "8888_app",
        "port": 8888,
        "cwd": _DIR,
        "py": sys.executable,
        "argv": ["-u", os.path.join(_DIR, "app.py")],
        "pattern": f"{_DIR}/app.py",
        "log_name": "8888.log"
    })
    # 2. 8개 봇의 app.py (UI) + bot.py (엔진)
    for b in BOTS:
        cwd_path = os.path.join(_ROOT, b)
        py_path = _venv_py(b)
        # UI
        targets.append({
            "name": f"{b}_ui",
            "port": int(b),
            "cwd": cwd_path,
            "py": py_path,
            "argv": ["-u", "-m", "streamlit", "run", "app.py", "--server.port", str(b), "--server.headless", "true"],
            "pattern": f"--server.port {b}",
            "log_name": f"{b}_ui.log"
        })
        # Engine
        targets.append({
            "name": f"{b}_bot",
            "port": None,
            "cwd": cwd_path,
            "py": py_path,
            "argv": ["-u", os.path.join(cwd_path, "bot.py")],
            "pattern": f"/{b}/bot.py",
            "log_name": f"{b}_bot.log"
        })
    return targets


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
    if port is None:
        return True
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def find_pids(pattern, name):
    """ps 출력에서 command에 pattern이 포함된 실제 타겟 PID 목록 반환."""
    pids = []
    try:
        out = subprocess.check_output(["ps", "-eo", "pid,command"], text=True, errors="replace")
        for line in out.splitlines()[1:]:
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                pid_str, cmd = parts
                match = False
                if name == "8888_app":
                    if "app.py" in cmd and "--server.port" not in cmd and "streamlit" not in cmd and "watchdog" not in cmd and "grep" not in cmd:
                        match = True
                else:
                    if pattern in cmd and "watchdog.py" not in cmd and "grep" not in cmd and "ps -eo" not in cmd:
                        match = True
                if match:
                    try:
                        pids.append(int(pid_str))
                    except ValueError:
                        pass
    except Exception as e:
        log(f"find_pids 오류: {e}")
    return pids


def kill_pids(pids, name):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
            log(f"🛑 [{name}] PID {pid} 종료 완료")
        except OSError:
            pass
    time.sleep(1.5)


def kill_port(port):
    if port is None:
        return
    try:
        out = subprocess.check_output(["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN"], text=True, errors="replace")
        for line in out.splitlines():
            pid_str = line.strip()
            if pid_str:
                try:
                    os.kill(int(pid_str), signal.SIGKILL)
                    log(f"🛑 포트 {port} 점유 PID {pid_str} 종료 완료")
                except OSError:
                    pass
    except Exception:
        pass
    time.sleep(1.5)


def launch(target):
    """해당 폴더에서 분리(start_new_session) 실행."""
    os.makedirs(LOG_DIR, exist_ok=True)
    out_path = os.path.join(LOG_DIR, target["log_name"])
    out = open(out_path, "a", encoding="utf-8")
    out.write(f"\n===== [{now()}] watchdog 실행: {target['name']} =====\n")
    out.flush()
    subprocess.Popen([target["py"]] + target["argv"], cwd=target["cwd"], stdout=out, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)


# [2026-08-23] DOWN을 **연속 2회** 봐야 재기동한다.
#
# 왜: `run.sh`는 구 프로세스를 죽이고 새로 띄우는데, 그 사이 몇 초의 공백이 있다.
# 워치독이 그 틈에 끼어들어 봇을 먼저 띄우면 run.sh가 띄운 쪽이 락에 막혀 죽고,
# **run.sh가 이미 로그를 .bak으로 밀어낸 뒤**라 살아남은 프로세스는 이름이 바뀐
# 파일에 계속 쓴다. 그러면 bot_engine.log는 몇 줄짜리 껍데기로 남아
# **봇이 죽은 것처럼 보인다** — 오늘 8408·8409를 그렇게 오진했다.
# 5분 주기이므로 한 번 넘기면 최대 5분 늦어지지만, 잘못 띄우는 것보다 낫다.
_down_streak = {}
DOWN_CONFIRM = 2


def _confirm_down(name):
    """DOWN을 연속으로 몇 번 봤는지 세고, 재기동해도 되는지 답한다."""
    n = _down_streak.get(name, 0) + 1
    _down_streak[name] = n
    if n < DOWN_CONFIRM:
        log(f"⏳ [{name}] DOWN {n}/{DOWN_CONFIRM}회 — 재기동 보류 "
            f"(수동 재기동 중일 수 있어 다음 주기에 다시 확인)")
        return False
    return True


def check_and_manage(target):
    name = target["name"]
    port = target["port"]
    pattern = target["pattern"]

    pids = find_pids(pattern, name)

    # 1. 중복 실행 (2개 이상의 PID 감지)
    if len(pids) > 1:
        log(f"⚠️ [{name}] 중복 실행 감지 ({len(pids)}개 PID: {pids}) -> 전체 종료 후 단일 클린 재기동")
        kill_pids(pids, name)
        if port is not None:
            kill_port(port)
        launch(target)
        return True

    # 2. 1개 PID 존재
    if len(pids) == 1:
        if port is not None:
            if port_alive(port):
                _down_streak.pop(name, None)
                return False  # 정상 유지
            else:
                log(f"⚠️ [{name}] PID({pids[0]}) 존재하나 포트({port}) DOWN -> 프로세스 종료 후 재기동")
                kill_pids(pids, name)
                kill_port(port)
                launch(target)
                return True
        else:
            _down_streak.pop(name, None)
            return False  # 엔진(bot.py) 1개 정상 유지

    # 3. 0개 PID
    if port is not None and port_alive(port):
        log(f"⚠️ [{name}] PID는 없으나 포트({port})가 사용 중 -> 해당 포트 점유 프로세스 종료 후 정상 단일 기동")
        kill_port(port)
    else:
        if not _confirm_down(name):
            return False
        log(f"❌ [{name}] DOWN {DOWN_CONFIRM}회 확인 -> 단일 기동")
    _down_streak.pop(name, None)
    launch(target)
    return True


PGUARD_INTERVAL = 3600          # 수익성 점검 주기(초) — 1시간
_last_pguard = 0.0


def run_profit_guard():
    """수익성 워치독(profit_guard.py) 실행.

    프로세스 생존 감시(본 워치독)와 성격이 달라 별도 주기로 돌린다. 매매이력이 쌓여야
    판정이 의미 있으므로 5분이 아니라 1시간 주기다. 실패해도 워치독 본체는 계속 돈다.
    """
    global _last_pguard
    if time.time() - _last_pguard < PGUARD_INTERVAL:
        return
    _last_pguard = time.time()
    script = os.path.join(BASE, "profit_guard.py") if "BASE" in globals() \
        else os.path.join(os.path.dirname(os.path.abspath(__file__)), "profit_guard.py")
    try:
        r = subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=600)
        tail = (r.stdout or r.stderr or "").strip().splitlines()[-3:]
        log("🩺 수익성 점검 실행 — " + " | ".join(tail))
    except Exception as e:
        log(f"⚠️ 수익성 점검 실행 실패: {str(e)[:150]}")


def run_config_sentinel():
    """테스트 조건 변조 감시·자동복원(config_sentinel.py).

    외부 도구(IDE 등)가 봇 폴더를 고쳐 역매매·자동스위칭이 되살아나는 사고가 있었다.
    조건이 고정돼 있어야 측정이 성립하므로 프로세스 감시와 같은 주기로 확인한다.
    실패해도 워치독 본체는 계속 돈다.
    """
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_sentinel.py")
    if not os.path.exists(script):
        return
    try:
        r = subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=120)
        out = (r.stdout or r.stderr or "").strip().splitlines()
        if out and "이상 없음" not in out[-1]:
            log("🛡 조건 감시 — " + " | ".join(out[-3:]))
    except Exception as e:
        log(f"⚠️ 조건 감시 실행 실패: {str(e)[:150]}")


def main():
    targets = build_targets()
    log(f"🚀 watchdog 시작 — 감시 대상 총 {len(targets)}개 (8888 + 봇 쌍), 주기 {CHECK_INTERVAL}초 (5분)"
        f" · 수익성 점검 {PGUARD_INTERVAL//60}분 주기 · 조건 감시 매 주기")
    while True:
        run_config_sentinel()
        run_profit_guard()
        launched_any = False
        for t in targets:
            try:
                if check_and_manage(t):
                    launched_any = True
            except Exception as e:
                log(f"⚠️ [{t['name']}] 검사/조치 중 오류: {str(e)[:150]}")
        if launched_any:
            log(f"⏳ 신규 기동 타겟 안정화 대기 ({WARMUP_AFTER_LAUNCH}초)...")
            time.sleep(WARMUP_AFTER_LAUNCH)
            for t in targets:
                pids = find_pids(t["pattern"], t["name"])
                status = f"PID {pids}" if pids else "DOWN"
                if t["port"]:
                    status += f" / PORT {'UP' if port_alive(t['port']) else 'WAIT/DOWN'}"
                log(f"  - [{t['name']}] 상태: {status}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
