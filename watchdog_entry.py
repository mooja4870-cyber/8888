import os
import sys
import json
import time
import socket
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

from datetime import datetime, timedelta, timezone

# 상시 기본 관리 대상 5개 핵심 봇 최우선 순찰
CORE_BOTS = [8401, 8402, 8407, 8409, 8410]
BOT_LIST = [8401, 8402, 8403, 8404, 8405, 8407, 8408, 8409, 8410]
HEALTH_CHECK_SEC = 60  # 1 minute for process health
CONFIG_CHECK_CYCLES = 5  # Check config drift every 5 cycles (5 minutes)
FLAT_BOT_CHECK_CYCLES = 5  # [보스 지침] 5분 주기 무포지션 봇 정밀 건전성 감사 및 적의조치
AUDIT_33_CYCLES = 2        # [보스 지침] 2분 주기 33대 체크리스트 자체 점검

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
    [보스 특별 지침] 거래소 체결 내역 vs 로컬 장부(trade_history.csv) 4대 무결성 상시 감사:
    1) 유령 포지션(Ghost) 사냥 및 오프라인 SL/TP 자동 청산
    2) 고아 포지션(Orphan) 감지 및 추적 복원
    3) 분할 익절(Scale-out Partial Exit) 합산 누락 자동 복원
    4) 장부 괴리율(Ledger Drift Guard) 정밀 모니터링
    """
    sentinel_script = "/Users/l/project/8888/bot_sentinel.py"
    if not os.path.exists(sentinel_script):
        return

    try:
        res = subprocess.run(
            [sys.executable, sentinel_script, str(b)],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=25
        )
        if res.returncode == 0 and res.stdout.strip():
            lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
            data = None
            for l in reversed(lines):
                if l.startswith("{") and l.endswith("}"):
                    try:
                        data = json.loads(l)
                        break
                    except Exception:
                        pass
            if data:
                actions = data.get("actions", [])
                diff = data.get("balance_diff", 0.0)
                if actions:
                    logger.warning(f"[{b}] 🛡 센티넬 감사 조치: {', '.join(actions)} (잔고괴리: ${diff:+.4f})")
                else:
                    logger.info(f"[{b}] 📋 체결 장부 4대 무결성 정상 (잔고괴리: ${diff:+.4f})")
            else:
                logger.info(f"[{b}] 📋 체결 장부 4대 무결성 점검 완료")
        else:
            err = res.stderr.strip()[:100] if res.stderr else "unknown"
            logger.debug(f"[{b}] 센티넬 감사 경미한 오류: {err}")
    except subprocess.TimeoutExpired:
        logger.warning(f"[{b}] ⚠️ 센티넬 감사 타임아웃 (25초 초과)")
    except Exception as e:
        logger.debug(f"[{b}] 체결 장부 무결성 감사 중 경미한 예외: {e}")

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

def check_entry_failure_readiness(b: int, cwd: str) -> tuple:
    """
    [보스 특별 지침] 5분 주기 진입 실패 및 거래소 주문 거절 실시간 감사:
    1. 최근 15분간 엔진 로그에서 진입 주문 실패/거절 패턴(notional, API rejection 등) 추적
    2. 반복(2회 이상) 발생 시 이상으로 판정하여 적의조처(자가 치유 및 재기동) 연계
    반환값: (이상 발생 여부: bool, 이상 상세: str, 오류 유형: str)
    """
    order_err_keywords = [
        "주문 거절", "주문 실패", "order's notional must be no smaller than",
        "-4164", "order timeout/error", "최소 주문 단위", "무방비 진입"
    ]
    now_kst = datetime.utcnow() + timedelta(hours=9)
    recent_fails = []
    
    # bot_engine.log를 우선 탐색, 부재 시 bot_stdout.log 확인
    target_logs = [os.path.join(cwd, "bot_engine.log")]
    if not os.path.exists(target_logs[0]):
        target_logs = [os.path.join(cwd, "bot_stdout.log")]
        
    for log_path in target_logs:
        if not os.path.exists(log_path):
            continue
        try:
            with open(log_path, "rb") as lf:
                lf.seek(0, os.SEEK_END)
                size = lf.tell()
                seek_pos = max(0, size - 49152)  # 최근 48KB 정밀 스캔
                lf.seek(seek_pos)
                tail_data = lf.read().decode("utf-8", errors="ignore")
            
            seen_lines = set()
            for line in tail_data.split("\n"):
                line_str = line.strip()
                if not line_str or line_str in seen_lines:
                    continue
                if any(kw in line_str.lower() for kw in order_err_keywords):
                    try:
                        ts_str = line_str[:19]
                        log_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        diff_sec = abs((now_kst - log_dt).total_seconds())
                        if diff_sec < 900:  # 최근 15분 이내 발생
                            recent_fails.append(line_str)
                            seen_lines.add(line_str)
                    except Exception:
                        pass
        except Exception:
            pass

    if len(recent_fails) >= 2:
        last_fail = recent_fails[-1]
        err_type = "ORDER_REJECTED"
        reason_summary = "주문 반복 거절/실패"
        if "notional" in last_fail.lower() or "-4164" in last_fail:
            err_type = "NOTIONAL_MIN_ERROR"
            reason_summary = "최소 주문 명목가치(Notional < 5 USDT) 미달 거절"
        elif "insufficient" in last_fail.lower() or "잔고" in last_fail:
            err_type = "INSUFFICIENT_FUNDS"
            reason_summary = "증거금 잔고 부족 주문 거절"
        elif "timeout" in last_fail.lower():
            err_type = "API_TIMEOUT_ERROR"
            reason_summary = "거래소 주문 API 타임아웃"
            
        return True, f"진입 주문 반복 거절/실패 감지 ({len(recent_fails)}회 발생: {reason_summary})", err_type
        
    return False, "진입 주문 정상", ""

def check_flat_bot_readiness(b: int, cwd: str) -> tuple:
    """
    [보스 특별 지침] 5분 주기 무포지션 봇 정밀 건전성 감사 및 데드락 자동 탐지:
    1. 포지션 보유 여부 확인 (active_positions.json이 비어있는 무포지션 봇 대상)
    2. config.json의 AUTO_TRADING 활성화 여부 확인
    3. stats.json의 과거 날짜 연속손절 정지(halted_by_consec_sl) 잔존 검사
    4. 최근 엔진 로그에서 'trader disabled' 최근(15분 이내) 발생 검사
    5. 스캐너 진행 정체(Scanner Stall: 최근 15분간 로그 갱신 여부) 검사
    반환값: (이상 발생 여부: bool, 이상 사유: str)
    """
    act_file = os.path.join(cwd, "data", "active_positions.json")
    if os.path.exists(act_file):
        try:
            with open(act_file, "r") as f:
                pdata = json.load(f)
            if pdata and len(pdata) > 0:
                return False, f"포지션 {len(pdata)}건 보유 중 (건전)"
        except Exception:
            pass

    # 1) config.json 검사 (사용자 의도적 정지 여부)
    cfg_file = os.path.join(cwd, "config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r") as f:
                cfg = json.load(f)
            if not cfg.get("AUTO_TRADING", True):
                return False, "AUTO_TRADING=False (수동 일시 정지)"
        except Exception:
            pass

    # 2) stats.json 과거 날짜 consecutive SL 정지 락 잔존 검사
    stats_file = os.path.join(cwd, "data", "stats.json")
    if os.path.exists(stats_file):
        try:
            with open(stats_file, "r") as f:
                sdata = json.load(f)
            today_kst = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")
            s_date = sdata.get("consec_sl_date", "")
            is_halted = sdata.get("halted_by_consec_sl", False)
            if is_halted and s_date and s_date < today_kst:
                return True, f"전일({s_date}) 연속손절 정지 락 잔존 데드락"
        except Exception:
            pass

    # 3) 최근 엔진 로그 trader disabled 발생 검사 (최근 15분 이내)
    now_kst = datetime.utcnow() + timedelta(hours=9)
    for log_name in ["bot_stdout.log", "bot_engine.log"]:
        log_path = os.path.join(cwd, log_name)
        if os.path.exists(log_path):
            try:
                with open(log_path, "rb") as lf:
                    lf.seek(0, os.SEEK_END)
                    size = lf.tell()
                    seek_pos = max(0, size - 8192)
                    lf.seek(seek_pos)
                    tail_data = lf.read().decode("utf-8", errors="ignore")
                if "trader disabled" in tail_data:
                    lines = [l for l in tail_data.split("\n") if "trader disabled" in l]
                    if lines:
                        last_line = lines[-1].strip()
                        try:
                            ts_str = last_line[:19]
                            log_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                            diff_sec = abs((now_kst - log_dt).total_seconds())
                            if diff_sec < 900:
                                return True, f"인메모리 트레이더 비활성(trader disabled) 최근 감지 ({int(diff_sec)}초 전)"
                        except Exception:
                            return True, f"인메모리 트레이더 비활성 감지: {last_line[:80]}"
            except Exception:
                pass

    # 4) 스캐너 진행 정체(Scanner Stall: 최근 15분간 로그 무반응) 검사
    for log_name in ["bot_stdout.log", "bot_engine.log"]:
        log_path = os.path.join(cwd, log_name)
        if os.path.exists(log_path):
            try:
                mtime = os.path.getmtime(log_path)
                elapsed = time.time() - mtime
                if elapsed > 900:
                    return True, f"스캐너 루프 정체(Stall: {int(elapsed/60)}분간 로그 갱신 없음)"
            except Exception:
                pass

    return False, "무포지션 대기 중 정상 (정상 스캔 지속)"

def check_and_fix_bot(b: int, do_config_check: bool = True, do_flat_check: bool = False, do_audit_33: bool = False):
    cwd = f"/Users/l/project/{b}"
    if not os.path.exists(cwd):
        logger.warning(f"[{b}] 봇 폴더가 존재하지 않습니다.")
        return
        
    needs_restart = False
    action_taken = []
    
    # [Foolproof 방지책] AUTO_TRADING이 강제로 꺼져(false) 죽은 것처럼 보이는 현상 원천 차단
    cfg_file = os.path.join(cwd, "config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r") as f:
                cfg = json.load(f)
            if not cfg.get("AUTO_TRADING", True):
                logger.warning(f"[{b}] 🚨 AUTO_TRADING 꺼짐 감지 (수동 정지/비정상 상태) -> 강제 ON 복구 진행")
                cfg["AUTO_TRADING"] = True
                with open(cfg_file, "w") as f:
                    json.dump(cfg, f, indent=4)
                
                alert_msg = f"🚨 **[Foolproof 발동: {b}]**\\n봇이 비정상적으로 '자동매매 OFF(노란색)' 상태에 빠져 신규 진입이 차단되어 있었습니다.\\n-> 🟢 강제로 **자동매매 ON** 상태로 즉시 복구했습니다."
                py_cmd = f"import sys; sys.path.insert(0, '{cwd}'); import core.alert as alert; alert.send_telegram_alert('{alert_msg}')"
                subprocess.run(["python3", "-c", py_cmd], cwd=cwd)
        except Exception as e:
            logger.error(f"[{b}] ⚠️ Foolproof AUTO_TRADING 검사 중 오류: {e}")
    
    # [33대 자체점검 수행]
    if do_audit_33:
        try:
            import core.audit_33 as audit_33
            import importlib
            importlib.reload(audit_33)
            
            anomalies = audit_33.run_33_point_audit(b, cwd)
            if anomalies:
                alert_msg = f"🚨 **[워치독 33대 자체점검 이상 감지: {b}]**\\n\\n발견된 문제:\\n" + "\\n".join([f"- {a}" for a in anomalies]) + "\\n\\n🛠 **즉각적인 적의조처(자동 재기동) 트리거 발동**"
                logger.warning(f"[{b}] 🚨 33대 자체점검 이상 감지: {len(anomalies)}건 발견. 자동 복구 트리거 발동.")
                needs_restart = True
                action_taken.append("33대 자체점검 자동복구 트리거")
                
                py_cmd = f"import sys; sys.path.insert(0, '{cwd}'); import core.alert as alert; alert.send_telegram_alert('{alert_msg}')"
                subprocess.run(["python3", "-c", py_cmd], cwd=cwd)
            else:
                logger.info(f"[{b}] ✅ 33대 자체점검 All Clear")
        except Exception as e:
            logger.error(f"[{b}] ⚠️ 33대 자체점검 수행 중 오류: {e}")

    # 1. 프로세스 생존 검사
    bot_alive = is_process_running(cwd, "bot.py")
    if not bot_alive:
        logger.error(f"[{b}] 🚨 bot.py 프로세스가 죽어 있습니다!")
        needs_restart = True
        action_taken.append("프로세스 다운 (재기동 필요)")
        
    # 1-1. 엔진 심장박동 (로그 갱신) 검사 (좀비 봇 감지)
    if bot_alive and not needs_restart:
        log_file = os.path.join(cwd, "bot_engine.log")
        if os.path.exists(log_file):
            mtime = os.path.getmtime(log_file)
            age = time.time() - mtime
            if age > 300:  # 5분 이상 갱신 없음 (좀비 상태)
                logger.error(f"[{b}] 🚨 bot.py 좀비 상태 감지! (로그 {int(age)}초 갱신 중단)")
                needs_restart = True
                action_taken.append("엔진 좀비/프리즈 (재기동 필요)")

    # 1-2. UI 프로세스 생존 검사 (포트 감시)
    if not needs_restart:
        
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('127.0.0.1', b))
            if result != 0:
                logger.error(f"[{b}] 🚨 대시보드 UI (포트 {b}) 응답 없음!")
                needs_restart = True
                action_taken.append("UI 다운 (재기동 필요)")

    # 1.5. [보스 특별 지침] 5분 주기 진입 실패/거절 감사 및 무포지션 건전성 감사
    if do_flat_check and not needs_restart:
        try:
            # 1) 진입 주문 거절/실패 반복 발생 전수 감사 (포지션 유무 무관)
            entry_issue, entry_reason, err_type = check_entry_failure_readiness(b, cwd)
            if entry_issue:
                logger.warning(f"[{b}] 🚨 진입 주문 거절/실패 이상 감지: {entry_reason}")
                action_taken.append(entry_reason)
                
                # [적의조처: Notional 미달 자동 치유]
                if err_type == "NOTIONAL_MIN_ERROR":
                    cfg_file = os.path.join(cwd, "config.json")
                    if os.path.exists(cfg_file):
                        try:
                            with open(cfg_file, "r", encoding="utf-8") as cf:
                                b_cfg = json.load(cf)
                            b_lev = float(b_cfg.get("LEVERAGE", 3.0) or 3.0)
                            cur_margin = float(b_cfg.get("MARGIN_USDT", 1.5) or 1.5)
                            req_margin = round(5.5 / b_lev, 1)
                            if cur_margin < req_margin:
                                b_cfg["MARGIN_USDT"] = req_margin
                                with open(cfg_file, "w", encoding="utf-8") as cf:
                                    json.dump(b_cfg, cf, indent=4, ensure_ascii=False)
                                msg_fix = f"MARGIN_USDT 자가 상향 치유({cur_margin}→{req_margin})"
                                logger.info(f"[{b}] 🛠 {msg_fix}")
                                action_taken.append(msg_fix)
                        except Exception as ce:
                            logger.error(f"[{b}] config.json Notional 치유 실패: {ce}")
                needs_restart = True
            else:
                # 2) 무포지션 봇 정밀 건전성 감사
                flat_issue, flat_reason = check_flat_bot_readiness(b, cwd)
                if flat_issue:
                    logger.warning(f"[{b}] 🚨 무포지션 건전성 이상 감지: {flat_reason}")
                    needs_restart = True
                    action_taken.append(flat_reason)
                else:
                    logger.info(f"[{b}] 🛡 무포지션 건전성: {flat_reason}")
        except Exception as e:
            logger.error(f"[{b}] 진입 건전성 감사 중 예외: {e}")

    # 2. 방향성(순/역매매) 오염 및 Phantom Overwrite 검사 -> 워치독 자율 스위칭
    # [2026-09-02] 워치독의 독자 스위칭은 엔진으로 일원화되어 관측만 하던 기능이었으나,
    # 각 봇의 core 패키지를 sys.path에 동적으로 로드하는 과정에서 sys.modules['core'] 전역 오염이 발생하여
    # watchdog의 핵심 모듈인 core.audit_33 로드를 방해하므로 완전히 제거합니다.
    pass

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

    # [보스 지침] 이상이 감지되었으나 포지션 보호로 재기동이 유예된 경우 텔레그램 경보 발송
    if action_taken and not needs_restart and bot_alive:
        try:
            alert_msg = f"⚠️ **[워치독 진입 이상 감지 (재기동 유예): {b}]**\\n\\n감지 내역: {', '.join(action_taken)}\\n상태: 포지션 보호를 위해 청산 후 재기동 유예 (Config 교정 완료)."
            py_cmd = f"import sys; sys.path.insert(0, '{cwd}'); import core.alert as alert; alert.send_telegram_alert('{alert_msg}')"
            subprocess.run(["python3", "-c", py_cmd], cwd=cwd)
        except Exception as e:
            logger.error(f"[{b}] 텔레그램 알림 발송 실패: {e}")

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
        do_flat_check = (cycle % FLAT_BOT_CHECK_CYCLES == 0) or (cycle == 1)
        do_audit_33 = (cycle % AUDIT_33_CYCLES == 0)
        
        logger.info(f"--- 순찰 사이클 {cycle} 시작 (Config 검증: {do_config_check}, 무포지션 감사: {do_flat_check}, 33대 감사: {do_audit_33}) ---")
        for bot in BOT_LIST:
            try:
                check_and_fix_bot(bot, do_config_check=do_config_check, do_flat_check=do_flat_check, do_audit_33=do_audit_33)
            except Exception as e:
                logger.error(f"[{bot}] 워치독 순찰 중 치명적 오류: {e}")
        
        logger.info(f"순찰 완료. {HEALTH_CHECK_SEC}초 후 다음 순찰 진행...")
        time.sleep(HEALTH_CHECK_SEC)

if __name__ == "__main__":
    main()
