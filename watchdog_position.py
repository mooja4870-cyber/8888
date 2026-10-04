#!/usr/bin/env python3
import os
import sys
import time
import datetime
import traceback
import subprocess
import requests
import signal

# Base Paths
BASE_DIR = "/Users/l/project"
BOTS = ["8401", "8402", "8403", "8404", "8405", "8408", "8410"]
LOG_FILE = os.path.join(BASE_DIR, "8888", "watchdog_position.log")
CHECK_INTERVAL = 20
SILENT_CRASH_TIMEOUT = 1800  # 30분
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5MB 자가 로테이션


import re

def load_error_dict():
    kws = []
    try:
        with open("/Users/l/project/8888/error_dict.txt", "r", encoding="utf-8") as f:
            for line in f:
                cl = line.strip()
                if len(cl) > 4:
                    kws.append(cl)
    except:
        pass
    return kws

ERROR_DICT_KEYWORDS = load_error_dict()

def fuzzy_match(kw, text):
    kw_clean = re.sub(r"[^a-zA-Z0-9가-힣]", "", kw.lower())
    text_clean = re.sub(r"[^a-zA-Z0-9가-힣]", "", text.lower())
    if len(kw_clean) >= 5 and kw_clean in text_clean:
        return True
    return False

ERROR_KEYWORDS = [
    "NameError", "Exception", "Traceback", "Order failed",
    "진입 실패", "position error", "rate limit", "Too Many Requests", "조회 실패"
]

FATAL_KEYWORDS = [
    "InsufficientBalance", "Margin mode", "Position mode"
]

# Webhook Caching (디스크 I/O 최적화)
_cached_webhook = None
def get_discord_webhook():
    global _cached_webhook
    if _cached_webhook is not None:
        return _cached_webhook
    try:
        with open(os.path.join(BASE_DIR, "8888", "discord_webhook.txt"), "r") as f:
            _cached_webhook = f.read().strip()
            return _cached_webhook
    except Exception:
        return None

def send_discord(msg):
    webhook = get_discord_webhook()
    if not webhook: return
    try:
        requests.post(webhook, json={"content": f"🚨 [POSITION V4] {msg}"}, timeout=5)
    except Exception:
        pass

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_SIZE:
            os.rename(LOG_FILE, LOG_FILE + ".bak")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def get_bot_process_info(bot_name):
    """PID와 CPU 점유율 반환"""
    try:
        output = subprocess.check_output(["ps", "-eo", "pid,pcpu,command"])
        for line in output.decode().strip().split('\n'):
            if "bot.py" in line and bot_name in line and "grep" not in line and "watchdog" not in line:
                parts = line.strip().split()
                if len(parts) >= 3:
                    try:
                        return int(parts[0]), float(parts[1])
                    except ValueError:
                        return int(parts[0]), 0.0
    except Exception:
        pass
    return None, 0.0

def check_log_for_errors(bot_name, last_offsets):
    engine_log = os.path.join(BASE_DIR, bot_name, "bot_engine.log")
    app_log = os.path.join(BASE_DIR, bot_name, "app.log")
    
    found_error, is_fatal, is_silent_crash, error_msg = False, False, False, ""
    current_time = time.time()
    latest_mtime = 0
    
    for log_path in [engine_log, app_log]:
        if not os.path.exists(log_path): continue
        try:
            mtime = os.path.getmtime(log_path)
            if mtime > latest_mtime: latest_mtime = mtime
                
            current_size = os.path.getsize(log_path)
            last_offset = last_offsets.get(log_path, current_size)
            
            if current_size < last_offset: last_offset = 0
            if current_size == last_offset: continue
                
            with open(log_path, "rb") as f:
                f.seek(last_offset)
                content = f.read().decode('utf-8', errors='ignore')
                last_offsets[log_path] = f.tell()
                
                for line in content.split('\n'):
                    if "[LOCK]" in line or "다른 트레이더 프로세스" in line: continue
                    if any(kw.lower() in line.lower() for kw in FATAL_KEYWORDS):
                        return True, True, False, line.strip()
                    if any(kw.lower() in line.lower() for kw in ERROR_KEYWORDS) or any(fuzzy_match(kw, line) for kw in ERROR_DICT_KEYWORDS):
                        if "[INFO]" in line and "Exception" not in line and "Error" not in line: continue
                        if "진입유실 방지" in line: continue
                        found_error = True
                        error_msg = line.strip()
        except Exception: pass
            
    if latest_mtime > 0 and (current_time - latest_mtime > SILENT_CRASH_TIMEOUT):
        return True, False, True, "Silent Crash: 30분 이상 로그 갱신 없음 (Deadlock)"
        
    return found_error, is_fatal, False, error_msg

def take_action(bot_name, error_msg, is_fatal=False):
    bot_dir = os.path.join(BASE_DIR, bot_name)
    cb_file, pause_file = os.path.join(bot_dir, ".circuit_breaker"), os.path.join(bot_dir, ".pause")
    
    if os.path.exists(cb_file): return
        
    pid, _ = get_bot_process_info(bot_name)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(3)
            pid2, _ = get_bot_process_info(bot_name)
            if pid2: os.kill(pid, signal.SIGKILL)
        except Exception: pass
            
    if is_fatal:
        log(f"[{bot_name}] 치명적 에러로 강제 Pause: {error_msg[:100]}")
        send_discord(f"봇 **{bot_name}** 치명적 진입 에러.\n사유: `{error_msg[:100]}`\n`.pause` 처리(수동 조치 요망).")
        try:
            with open(pause_file, "w") as f: f.write("Fatal error V4")
        except Exception: pass
        return
        
    log(f"[{bot_name}] 진입 문제 감지, 재기동 중: {error_msg[:100]}")
    send_discord(f"봇 **{bot_name}** 포지션 진입 문제/다운.\n사유: `{error_msg[:100]}`\n자동 재시작 수행.")
    
    try:
        if os.path.exists(pause_file): os.remove(pause_file)
    except Exception: pass
            
    run_script = os.path.join(bot_dir, "run.sh")
    if os.path.exists(run_script):
        try: subprocess.Popen(["bash", "run.sh"], cwd=bot_dir, start_new_session=True)
        except Exception as e: log(f"[{bot_name}] 재기동 실행 실패: {e}")
    else:
        log(f"[{bot_name}] run.sh 누락.")

def main():
    log("=== Position Entry Watchdog Started (God Mode V4) ===")
    send_discord("20초 주기 포지션 진입 점검 워치독 가동 (1만항목 기반 God Mode V4)")
    last_action_time = {bot: 0 for bot in BOTS}
    last_offsets = {}
    last_heartbeat_time = time.time()
    
    for bot in BOTS:
        for lg in ["bot_engine.log", "app.log"]:
            lp = os.path.join(BASE_DIR, bot, lg)
            try:
                if os.path.exists(lp): last_offsets[lp] = os.path.getsize(lp)
            except Exception: pass
    
    while True:
        try:
            current_time = time.time()
            restarted_in_this_cycle = False # 글로벌 딜레이 제어(IP 밴 방지)
            
            if current_time - last_heartbeat_time >= 60:
                send_discord("✅ 1분 정기 보고: 진입/포지션 에러 감시 중 (전체 봇 정상 동작)")
                last_heartbeat_time = current_time
            
            for bot in BOTS:
                bot_dir = os.path.join(BASE_DIR, bot)
                if os.path.exists(os.path.join(bot_dir, ".circuit_breaker")) or os.path.exists(os.path.join(bot_dir, ".pause")):
                    continue
                    
                pid, pcpu = get_bot_process_info(bot)
                
                # V4 CPU Spike 방어
                if pid and pcpu > 95.0:
                    if current_time - last_action_time[bot] > 120:
                        log(f"[{bot}] 100% CPU Spike(Zombie) 감지됨. 강제 재시작.")
                        take_action(bot, f"CPU 폭주: {pcpu}%")
                        last_action_time[bot] = current_time
                        restarted_in_this_cycle = True
                        time.sleep(10) # API DDoS 방지
                    continue
                
                if not pid:
                    if current_time - last_action_time[bot] > 120:
                        take_action(bot, "프로세스 중단(Down)")
                        last_action_time[bot] = current_time
                        for lg in ["bot_engine.log", "app.log"]: last_offsets[os.path.join(BASE_DIR, bot, lg)] = 0
                        restarted_in_this_cycle = True
                        time.sleep(10) # 글로벌 딜레이
                    continue
                
                has_err, is_fatal, is_silent, msg = check_log_for_errors(bot, last_offsets)
                if has_err or is_silent:
                    if current_time - last_action_time[bot] > 120:
                        take_action(bot, msg, is_fatal)
                        last_action_time[bot] = current_time
                        for lg in ["bot_engine.log", "app.log"]: last_offsets[os.path.join(BASE_DIR, bot, lg)] = 0
                        restarted_in_this_cycle = True
                        time.sleep(10)
                        
            # 만약 연쇄 재시작이 없었더라도 기본 대기
            if not restarted_in_this_cycle:
                time.sleep(CHECK_INTERVAL)
                
        except Exception as e:
            log(f"Watchdog V4 Main Loop Error: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
