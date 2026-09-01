import os
import sys
import json
import time
import subprocess
import logging

# Set up logging for the watchdog
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("/Users/l/project/8888/watchdog_entry.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Watchdog")

BOT_LIST = [8401, 8402, 8403, 8404, 8405, 8407, 8408, 8409, 8410]
HEALTH_CHECK_SEC = 60  # 1 minute for process health
CONFIG_CHECK_CYCLES = 5  # Check config drift every 5 cycles (5 minutes)

def is_process_running(cwd: str, script_name: str) -> bool:
    """Check if a specific script is running within the given working directory."""
    try:
        # pgrep -f matches full command line
        output = subprocess.check_output(f"pgrep -f '{script_name}'", shell=True, text=True)
        # We need to make sure it's running IN the specific bot directory
        pids = output.strip().split('\n')
        for pid in pids:
            if not pid: continue
            try:
                # Use lsof to check the CWD of the process, or just check ps output
                ps_out = subprocess.check_output(f"ps -p {pid} -o command=", shell=True, text=True)
                # This is a bit tricky on macOS. A simpler way is to check if there's ANY bot.py running 
                # from that specific path.
                lsof_out = subprocess.check_output(f"lsof -p {pid} | grep cwd", shell=True, text=True)
                if cwd in lsof_out:
                    return True
            except:
                pass
    except subprocess.CalledProcessError:
        pass
    return False

def check_and_fix_bot(b: int, do_config_check: bool = True):
    cwd = f"/Users/l/project/{b}"
    if not os.path.exists(cwd):
        logger.warning(f"[{b}] 봇 폴더가 존재하지 않습니다.")
        return

    sys.path.insert(0, cwd)
    
    needs_restart = False
    action_taken = []

    # 1. 프로세스 생존 검사
    bot_alive = is_process_running(cwd, "bot.py")
    if not bot_alive:
        logger.error(f"[{b}] 🚨 bot.py 프로세스가 죽어 있습니다!")
        needs_restart = True
        action_taken.append("프로세스 다운 (재기동 필요)")

    # 2. 방향성(순/역매매) 오염 및 Phantom Overwrite 검사 -> 워치독 자율 스위칭
    if do_config_check:
        import importlib
        try:
            import core.history_helper as hh
            importlib.reload(hh)
            
            # Load local trades
            orig_cwd = os.getcwd()
            os.chdir(cwd)
            raw_trades = hh.load_local_trade_history()
            os.chdir(orig_cwd)
            
            paired = hh.aggregate_and_pair_trades(raw_trades)
            closed_trades = [p for p in paired if p.get("status") == "청산 완료"]
            closed_trades.sort(key=lambda x: x.get("exit_time", ""))

            N = len(closed_trades)
            
            cfg_file = os.path.join(cwd, "config.json")
            state_file = os.path.join(cwd, "data", "switch_state.json")
            
            with open(cfg_file, "r") as f:
                cfg = json.load(f)

            actual_mode = cfg.get("USE_BLUEFROG", False)
            
            # 1) 기존 스위칭 정보 로드
            last_switched_on_count = 0
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r") as sf:
                        sdata = json.load(sf)
                    last_switched_on_count = sdata.get("last_switched_on_count", 0)
                except:
                    pass

            expected_mode = actual_mode
            should_switch = False
            
            # 2) 현재 모드에서 발생한 새로운 거래 내역만 검사
            if N > last_switched_on_count:
                recent_trades = closed_trades[last_switched_on_count:]
                
                # 3연패 조건 검사
                if len(recent_trades) >= 3 and all(float(t.get("pnl_usdt") or 0.0) < 0.0 for t in recent_trades[-3:]):
                    should_switch = True
                # 최근 5번 중 3번 패배 조건 검사
                elif len(recent_trades) >= 5:
                    losses = sum(1 for t in recent_trades[-5:] if float(t.get("pnl_usdt") or 0.0) < 0.0)
                    if losses >= 3:
                        should_switch = True
            
            # 3) 스위치 조건이 충족되면 모드를 뒤집고 상태 저장 (재기동 유도)
            if should_switch:
                expected_mode = not actual_mode
                logger.warning(f"[{b}] 🚨 방향성 스위칭 조건 충족! (현재: {actual_mode} ➡️ 스위칭: {expected_mode})")
                needs_restart = True
                action_taken.append(f"연패에 따른 워치독 강제 스위칭 조치 ({actual_mode} ➡️ {expected_mode})")
                
                last_switched_on_count = N
                try:
                    os.makedirs(os.path.dirname(state_file), exist_ok=True)
                    with open(state_file, "w") as sf:
                        json.dump({"last_switched_on_count": last_switched_on_count}, sf, indent=2)
                except Exception as e:
                    logger.error(f"[{b}] 상태 저장 실패: {e}")

        except Exception as e:
            logger.error(f"[{b}] ⚠️ 내역 검증 중 오류: {e}")
        finally:
            sys.path.pop(0)

    # 2.5. 포지션 보유 확인 (사살 유예 로직)
    if needs_restart and bot_alive:
        active_pos_file = os.path.join(cwd, "data", "active_positions.json")
        try:
            if os.path.exists(active_pos_file):
                with open(active_pos_file, "r") as pf:
                    pdata = json.load(pf)
                if len(pdata) > 0:
                    logger.warning(f"[{b}] 🛡 포지션({len(pdata)}건) 보유 확인! 트레일링 스탑 보호를 위해 재기동 유예 및 교정 지연(Deferred Patch).")
                    needs_restart = False
        except Exception as e:
            logger.error(f"[{b}] ⚠️ 포지션 상태 확인 실패: {e}")

    # 3. 조치 (재기동 및 교정)
    if needs_restart:
        logger.info(f"[{b}] 🛠 적의조처 실행: Config 교정 및 2-Step 재부팅...")
        
        # [Phase 2] 이 순간에 비로소 디스크를 교정하여 상태 비동기화를 완벽 방어
        if do_config_check and 'cfg' in locals() and 'expected_mode' in locals() and cfg.get("USE_BLUEFROG", False) != expected_mode:
            cfg["USE_BLUEFROG"] = expected_mode
            with open(cfg_file, "w") as f:
                json.dump(cfg, f, indent=4)

        # [Phase 2] 2-Step Graceful Shutdown은 각 봇의 run.sh 내부 로직에 이미 완벽하게 구현되어 있습니다.
        # 전역 pkill은 다른 봇을 학살하므로 절대 사용하지 않고 run.sh에 위임합니다.
        subprocess.run("bash run.sh > /dev/null 2>&1", shell=True, cwd=cwd)
        logger.info(f"[{b}] ✅ 재기동 완료. 조치 내역: {', '.join(action_taken)}")
        
        # API Rate Limit (밴) 방지를 위한 지연 재기동 (Staggered Restart)
        logger.info(f"[{b}] API 보호를 위해 5초 대기 후 다음 봇 순찰로 넘어갑니다...")
        time.sleep(5)
        
        # 텔레그램 알림 발송 (각 봇의 폴더 내에서 독립된 프로세스로 실행하여 캐싱 방지)
        try:
            alert_msg = f"🚨 **[워치독 긴급 조치: {b}]**\\n\\n발견된 문제: {', '.join(action_taken)}\\n조치: 2-Step Graceful 재기동 완료."
            py_cmd = f"import sys; sys.path.insert(0, '{cwd}'); import core.alert as alert; alert.send_telegram_alert('{alert_msg}')"
            subprocess.run(["python3", "-c", py_cmd], cwd=cwd)
        except Exception as e:
            logger.error(f"[{b}] 텔레그램 알림 발송 실패: {e}")
    else:
        logger.info(f"[{b}] 정상 작동 중")

def main():
    logger.info("==========================================")
    logger.info("🐶 Watchdog System Started (Profitability Guard Active)")
    logger.info("==========================================")
    cycle = 0
    while True:
        cycle += 1
        do_config_check = (cycle % CONFIG_CHECK_CYCLES == 1) or (CONFIG_CHECK_CYCLES == 1)
        
        logger.info(f"--- 순찰 사이클 {cycle} 시작 (Config 검증: {do_config_check}) ---")
        for bot in BOT_LIST:
            try:
                check_and_fix_bot(bot, do_config_check)
            except Exception as e:
                logger.error(f"[{bot}] 워치독 순찰 중 치명적 오류: {e}")
        
        logger.info(f"순찰 완료. {HEALTH_CHECK_SEC}초 후 다음 순찰 진행...")
        time.sleep(HEALTH_CHECK_SEC)

if __name__ == "__main__":
    main()
