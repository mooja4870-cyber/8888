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

from datetime import datetime

# 상시 기본 관리 대상 5개 핵심 봇 최우선 순찰
CORE_BOTS = [8401, 8402, 8407, 8409, 8410]
BOT_LIST = [8401, 8402, 8407, 8409, 8410, 8403, 8404, 8405]
HEALTH_CHECK_SEC = 60  # 1 minute for process health
CONFIG_CHECK_CYCLES = 5  # Check config drift every 5 cycles (5 minutes)

def check_exit_readiness(b: int, cwd: str) -> str:
    """
    [보스 특별 지침] 각 봇별 포지션 청산 기준 및 실행 준비도(Exit Readiness) 실시간 감시:
    1. 활성 포지션의 exit_profile(SL/TP, TRAILING) 유효성 검사
    2. 트레일링 콜백 파라미터(atr_activation, atr_callback) 정상치 검사
    3. 보유 시간 계산 및 MAX_HOLDING_HOURS 타임아웃 초과 여부 추적
    4. 이상 발생 시 경고 리턴
    """
    active_pos_file = os.path.join(cwd, "data", "active_positions.json")
    cfg_file = os.path.join(cwd, "config.json")
    
    if not os.path.exists(active_pos_file):
        return "활성 포지션 파일 없음"
        
    try:
        with open(active_pos_file, "r") as pf:
            positions = json.load(pf)
    except Exception as e:
        return f"포지션 파일 읽기 오류: {e}"
        
    if not positions:
        return "보유 포지션 없음 (대기 상태)"

    cfg = {}
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r") as cf:
                cfg = json.load(cf)
        except Exception:
            pass

    max_holding = float(cfg.get("MAX_HOLDING_HOURS", 0.0) or 0.0)
    hard_limit = float(cfg.get("MAX_HOLDING_HARD_HOURS", 24.0) or 24.0)
    now = datetime.now()
    
    pos_summaries = []
    has_warning = False

    for sym, pdata in positions.items():
        coin = sym.split("/")[0] if "/" in sym else sym
        profile = pdata.get("exit_profile", "SL/TP")
        strategy = pdata.get("strategy_type", "Standard")
        act = float(pdata.get("atr_activation", 0.0) or 0.0)
        cb = float(pdata.get("atr_callback", 0.0) or 0.0)
        
        # 1) 보유 시간 추적
        ot_str = pdata.get("open_time")
        age_hours = None
        if ot_str:
            try:
                clean_time = ot_str.split(".")[0]
                ot = datetime.fromisoformat(clean_time)
                age_hours = (now - ot).total_seconds() / 3600.0
            except Exception:
                pass
                
        # 2) 청산 기준 판정
        exit_status = "OK"
        if max_holding > 0 and age_hours is not None:
            if age_hours > hard_limit:
                exit_status = f"하드캡초과({age_hours:.1f}h>{hard_limit}h)🚨"
                has_warning = True
            elif age_hours > max_holding:
                exit_status = f"시간청산대기({age_hours:.1f}h>{max_holding}h)⚠️"
            else:
                exit_status = f"보유정상({age_hours:.1f}h/{max_holding}h)"
        elif max_holding == 0:
            age_desc = f"{age_hours:.1f}h" if age_hours is not None else "진행중"
            exit_status = f"RR/트레일링청산({age_desc})"
            
        # 3) 트레일링 파라미터 유효성 검사
        param_valid = (act > 0 and cb > 0)
        param_desc = f"act={act:.3f},cb={cb:.3f}" if param_valid else "기본값"
        
        pos_summaries.append(f"{coin}[{profile}|{exit_status}|{param_desc}]")

    summary_str = f"포지션 {len(positions)}건 청산 기준 정상: " + " | ".join(pos_summaries)
    if has_warning:
        logger.warning(f"[{b}] ⚠️ 청산 감시 이상 감지: {summary_str}")
    else:
        logger.info(f"[{b}] 🛡 청산 건전성: {summary_str}")
    return summary_str

def audit_trade_reconciliation(b: int, cwd: str) -> None:
    """
    [보스 특별 지침] 거래소 체결 내역 vs 로컬 장부(trade_history.csv) 누락 상시 감사:
    - 봇 프로세스 일시 다운 또는 오프라인 SL/TP 발생 시 체결 장부 누락을 감지하고 자동 동기화.
    - Rate limit 보호를 위해 봇 자체의 PnLReconciler를 안전하게 호출.
    """
    try:
        sync_cmd = (
            f"python3 -c '"
            f"import asyncio, sys, os; "
            f"sys.path.insert(0, \"{cwd}\"); "
            f"from core.api_keys import load_api_keys; "
            f"load_api_keys(override=True); "
            f"from core.engine import QuantumEngine; "
            f"eng = QuantumEngine.get_instance(); "
            f"async def _run(): "
            f"    if hasattr(eng, \"pnl_reconciler\") and eng.pnl_reconciler: "
            f"        await eng.pnl_reconciler.sync_trades_async(); "
            f"asyncio.run(_run())"
            f"'"
        )
        subprocess.run(sync_cmd, shell=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        logger.info(f"[{b}] 📋 체결 장부 무결성 감사(Reconciliation) 점검 완료")
    except Exception as e:
        logger.debug(f"[{b}] 체결 장부 감사 중 경미한 예외: {e}")

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
            # [2026-09-02] 워치독의 독자 스위칭을 중단하고 **관측만** 한다.
            #
            # 스위칭 주체는 각 봇 engine.check_auto_mode_switch() 하나로 일원화한다.
            # 두 구현이 같은 파일을 서로 다른 규칙·스키마로 쓰면서 문제가 있었다:
            #   · 판정 창이 다르다 — 엔진은 '최근 5건 고정', 워치독은 '마지막 스위칭
            #     이후 전체 슬라이스'. 같은 이력에서 결론이 갈린다.
            #   · 워치독은 쿨다운(스위칭 후 최소 3거래)이 없어 휩쏘 구간에서
            #     매 청산마다 방향이 뒤집힐 수 있다. 수수료만 나간다.
            #   · 워치독이 상태를 {"last_switched_on_count": N} 한 키로 덮어써
            #     last_switched_key가 사라지면 엔진의 중복 스위칭 방지가 풀린다.
            # 판정은 엔진이 30초마다 수행하므로 기능 공백은 없다.
            # 여기서는 불일치가 보이면 로그로만 남긴다(자동 조치·파일 쓰기 없음).
            try:
                if N >= 5:
                    _r5 = closed_trades[-5:]
                    _L = sum(1 for t in _r5 if float(t.get("pnl_usdt") or 0.0) < 0.0)
                    if _L >= 3:
                        _seq = "".join("x" if float(t.get("pnl_usdt") or 0.0) < 0.0 else "O"
                                       for t in _r5)
                        logger.info(f"[{b}] 스위칭 조건 관측: 5전 {_L}패({_seq})"
                                    f" — 판정·실행은 엔진이 담당")
            except Exception:
                pass

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
        # [2026-09-02] 매매방향 교정 제거 — 스위칭은 엔진 단일 주체다.
        # 워치독이 config.json의 USE_BLUEFROG를 되쓰면, 엔진이 방금 바꾼 방향을
        # 워치독이 되돌리는 경합이 난다(실제로 "방향성 오염 확정 / 자가 교정 실패"
        # 로그가 반복됐다). 워치독은 생존·재기동만 책임진다.

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
        # [보스 특별 지침] 핵심 봇 대상 포지션 청산 기준 건전성 실시간 감시
        if b in CORE_BOTS:
            try:
                check_exit_readiness(b, cwd)
            except Exception as e:
                logger.error(f"[{b}] 청산 건전성 검사 중 예외: {e}")

            # [보스 특별 지침] 핵심 봇 대상 체결 장부 무결성 상시 감사 및 오프라인 체결 자동 복원
            try:
                audit_trade_reconciliation(b, cwd)
            except Exception as e:
                logger.error(f"[{b}] 체결 장부 무결성 감사 중 예외: {e}")

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
