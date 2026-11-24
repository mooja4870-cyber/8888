import os
import re
import sys
import json
import time
import socket
import subprocess
import logging

BASE_8888 = os.path.dirname(os.path.abspath(__file__))
if BASE_8888 not in sys.path:
    sys.path.insert(0, BASE_8888)
from watchdog_common import (
    bot_restart_locked,
    clear_proactive_alert,
    is_external_network_down,
    is_maintenance_active,
    load_proactive_alerts,
    prune_expired_proactive_alerts,
    record_proactive_alert,
    update_watchdog_heartbeat,
)
from core.autonomous_auditor import (
    check_stale_code_sync,
    check_log_fd_and_pid_lock_integrity,
    run_all_autonomous_audits,
)
from core.exchange_infra_auditor import run_exchange_infra_audit
from core.portfolio_risk_auditor import run_portfolio_risk_audit
from core.security_ops_auditor import run_security_ops_audit

_ENTRY_LOG = os.path.join(BASE_8888, "watchdog_entry.log")
_stdout_redirected = False
try:
    if os.path.exists(_ENTRY_LOG):
        _s1, _s2 = os.fstat(sys.stdout.fileno()), os.stat(_ENTRY_LOG)
        _stdout_redirected = (_s1.st_dev == _s2.st_dev and _s1.st_ino == _s2.st_ino)
except Exception:
    _stdout_redirected = False

# Avoid duplicate log lines when watchdog_keeper.sh already redirects stdout -> watchdog_entry.log
_handlers = [logging.StreamHandler(sys.stdout)] if _stdout_redirected else [
    logging.FileHandler(_ENTRY_LOG),
    logging.StreamHandler(sys.stdout),
]
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=_handlers,
)
logger = logging.getLogger("Watchdog")

from datetime import datetime, timedelta, timezone

# 상시 기본 관리 대상 9개 핵심 봇 최우선 순찰 + 가동 9개 봇 전수 생존/Foolproof 감시
CORE_BOTS = [8401, 8402, 8403, 8404, 8405, 8407, 8408, 8409, 8410]
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

_SENTINEL_HIST_FILE = os.path.join(BASE_8888, "data", "sentinel_action_history.json")
_ENTRY_ERR_TRACKER_FILE = os.path.join(BASE_8888, "data", "entry_error_tracker.json")


def _load_json_safe(path: str, default: dict) -> dict:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
    except Exception:
        pass
    return dict(default)


def _save_json_atomic(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _track_sentinel_actions(bot_id: str, actions: list, window_sec: int = 1800) -> list:
    """Record sentinel actions and return (bucket, count) pairs repeating >=3x within 30m."""
    now = time.time()
    hist = _load_json_safe(_SENTINEL_HIST_FILE, {})
    bhist = hist.get(bot_id)
    if not isinstance(bhist, dict):
        bhist = {}

    pruned = {}
    for k, ts_list in bhist.items():
        if isinstance(ts_list, list):
            kept = [float(t) for t in ts_list if (now - float(t or 0.0)) <= window_sec]
            if kept:
                pruned[k] = kept

    for act in (actions or []):
        bucket = re.sub(r"\(.*?\)", "", str(act)).strip()[:60]
        if not bucket:
            continue
        pruned.setdefault(bucket, []).append(now)

    hist[bot_id] = pruned
    try:
        _save_json_atomic(_SENTINEL_HIST_FILE, hist)
    except Exception:
        pass
    return [(k, len(v)) for k, v in pruned.items() if len(v) >= 3]


def _record_and_count_entry_errors(bot_id: str, events: list, window_sec: int = 3600) -> tuple:
    """Persist hard entry rejection events across restarts and return (count, latest_type, latest_msg)."""
    now = time.time()
    tracker = _load_json_safe(_ENTRY_ERR_TRACKER_FILE, {})
    brec = tracker.get(bot_id)
    if not isinstance(brec, list):
        brec = []
    brec = [e for e in brec if isinstance(e, dict) and (now - float(e.get("ts") or 0.0)) <= window_sec]
    existing_keys = {(e.get("log_ts"), e.get("err_type")) for e in brec}
    for log_ts, err_type, msg in (events or []):
        if (log_ts, err_type) not in existing_keys:
            brec.append({"ts": now, "log_ts": log_ts, "err_type": err_type, "msg": msg[:180]})
            existing_keys.add((log_ts, err_type))
    tracker[bot_id] = brec[-30:]
    try:
        _save_json_atomic(_ENTRY_ERR_TRACKER_FILE, tracker)
    except Exception:
        pass
    if not brec:
        return 0, "", ""
    return len(brec), brec[-1].get("err_type", ""), brec[-1].get("msg", "")


def audit_trade_reconciliation(b: int, cwd: str) -> None:
    """
    [보스 특별 지침] 거래소 체결 내역 vs 로컬 장부(trade_history.csv) 4대 + Aegis V6(M15/M21/M23) 무결성 상시 감사
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
        data = None
        if res.stdout.strip():
            lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
            for l in reversed(lines):
                if l.startswith("{") and l.endswith("}"):
                    try:
                        data = json.loads(l)
                        break
                    except Exception:
                        pass

        if data and data.get("error"):
            auth_err = str(data.get("auth_error") or "").strip()
            if auth_err:
                logger.error(f"[{b}] 🔐 [M23 인증 오류] {auth_err}")
                record_proactive_alert(
                    str(b), "sentinel_auth_error", "CRITICAL",
                    "거래소 API 인증/IP/권한 오류", auth_err,
                    "거래소 API 키 만료 및 서버 IP 화이트리스트 즉시 점검 필요",
                    cooldown_sec=3600, notify_discord=True,
                )
            else:
                logger.warning(f"[{b}] ⚠️ 센티넬 초기화 오류: {data.get('error')}")
            return

        if res.returncode == 0 and data:
            actions = data.get("actions", [])
            diff = data.get("balance_diff", 0.0)
            unprot = data.get("unprotected_positions") or []
            prot_errs = data.get("protection_check_errors") or []
            prot_mis = data.get("protection_mismatches") or []
            liq_warns = data.get("liq_warnings") or []
            mm_warns = data.get("margin_mode_warnings") or []
            orphan_algos = data.get("orphan_algo_orders") or []
            stale_oo = data.get("stale_open_orders") or []
            dust_pos = data.get("dust_positions") or []
            adl_warns = data.get("adl_warnings") or []
            basis_warns = data.get("basis_warnings") or []
            unauth_pos = data.get("unauthorized_positions") or []
            sec_warns = data.get("security_warnings") or []
            auth_err = str(data.get("auth_error") or "").strip()

            if auth_err:
                record_proactive_alert(
                    str(b), "sentinel_auth_error", "CRITICAL",
                    "거래소 API 인증/IP/권한 오류", auth_err,
                    "거래소 API 키 및 IP 화이트리스트 즉시 점검 필요",
                    cooldown_sec=3600, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_auth_error")

            if unprot:
                logger.warning(f"[{b}] 🚨 [보호주문 누락] 실 포지션 보호주문 미감지: {unprot}")
                record_proactive_alert(
                    str(b), "sentinel_unprotected_position", "CRITICAL",
                    "실 포지션 보호주문(SL/TP) 누락 감지",
                    f"대상 심볼: {', '.join(unprot)}",
                    "거래소 OCO / STOP_MARKET 주문 존재 여부 즉시 점검 필요",
                    cooldown_sec=1800, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_unprotected_position")

            if prot_mis:
                logger.warning(f"[{b}] 🚨 [M15 보호주문 불일치] {prot_mis}")
                record_proactive_alert(
                    str(b), "sentinel_protection_mismatch", "CRITICAL",
                    "보호주문 수량·방향·청산가 내측 정합 이상",
                    " | ".join(str(x) for x in prot_mis),
                    "포지션 전량 보호 및 SL 가격이 청산가 안쪽에 있는지 즉시 확인 필요",
                    cooldown_sec=1800, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_protection_mismatch")

            if prot_errs:
                logger.warning(f"[{b}] ⚠️ [결함수정: 보호주문 조회실패] {prot_errs}")
                record_proactive_alert(
                    str(b), "sentinel_protection_check_error", "WARN",
                    "보호주문 API 조회 실패 (Fail-Open 차단)",
                    " | ".join(f"{x.get('symbol')}:{x.get('error')}" for x in prot_errs),
                    "보호주문 존재 확인 불가 — API 상태 점검 필요",
                    cooldown_sec=1800, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_protection_check_error")

            if liq_warns:
                crit_liq = any(str(w.get("severity")) == "CRITICAL" for w in liq_warns)
                desc = " | ".join(
                    f"{w.get('symbol')}(dist={w.get('liq_dist_pct','?')}%, mgn={w.get('okx_mgn_ratio', w.get('bnc_margin_ratio', '?'))})"
                    for w in liq_warns
                )
                logger.warning(f"[{b}] 🚨 [M15 청산거리/마진 경보] {desc}")
                record_proactive_alert(
                    str(b), "sentinel_liquidation_risk", "CRITICAL" if crit_liq else "WARN",
                    "청산가 근접 / 유지마진 위험", desc,
                    "강제청산 위험 구간 접근 — 증거금 추가 또는 비중 축소 승인 검토 필요",
                    cooldown_sec=1800 if crit_liq else 3600, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_liquidation_risk")

            if mm_warns:
                desc = " | ".join(f"{w.get('symbol')}(설정={w.get('expected')}, 실제={w.get('actual')})" for w in mm_warns)
                record_proactive_alert(
                    str(b), "sentinel_margin_mode_drift", "WARN",
                    "마진 모드 이탈(Cross vs Isolated) 감지", desc,
                    "거래소 포지션 마진 모드 확인 필요", cooldown_sec=3600, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_margin_mode_drift")

            if orphan_algos:
                desc = ", ".join(f"{x.get('instId')}({x.get('ordType')})" for x in orphan_algos[:5])
                record_proactive_alert(
                    str(b), "sentinel_orphan_algo", "WARN",
                    f"무포지션 고아 알고주문 {len(orphan_algos)}건 잔류", desc,
                    "청산 후 잔여 OCO/조건부 주문 확인 및 정리 권고", cooldown_sec=3600, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_orphan_algo")

            if stale_oo:
                desc = ", ".join(f"{x.get('symbol')}({x.get('age_min')}m)" for x in stale_oo[:5])
                record_proactive_alert(
                    str(b), "sentinel_stale_open_order", "WARN",
                    f"장기 방치 미체결 지정가 {len(stale_oo)}건", desc,
                    "10분 이상 미체결 주문의 증거금 점유 확인 권고", cooldown_sec=3600, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_stale_open_order")

            if dust_pos:
                desc = ", ".join(f"{x.get('symbol')}(${x.get('notional_usdt')})" for x in dust_pos[:5])
                record_proactive_alert(
                    str(b), "sentinel_dust_position", "WARN",
                    f"미세 잔고(Dust) 포지션 {len(dust_pos)}건", desc,
                    "최소주문금액 미만 잔고 정리 검토 권고", cooldown_sec=21600, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_dust_position")

            if adl_warns:
                crit_adl = any(str(w.get("severity")) == "CRITICAL" for w in adl_warns)
                desc = " | ".join(f"{w.get('symbol')}(adl={w.get('adl_rank')}/{w.get('max_rank')}, basis={w.get('basis_pct')}%)" for w in adl_warns)
                record_proactive_alert(
                    str(b), "sentinel_adl_risk", "CRITICAL" if crit_adl else "WARN",
                    "ADL(자동 디레버리징) 우선순위 고위험", desc,
                    "거래소 강제 디레버리징 대상 근접 — 익절/청산 타이밍 예의주시 필요",
                    cooldown_sec=3600 if crit_adl else 14400, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_adl_risk")

            if basis_warns:
                crit_b = any(str(w.get("severity")) == "CRITICAL" for w in basis_warns)
                desc = " | ".join(f"{w.get('symbol')}(basis={w.get('basis_pct')}%)" for w in basis_warns)
                record_proactive_alert(
                    str(b), "sentinel_basis_divergence", "CRITICAL" if crit_b else "WARN",
                    "Mark-Index 가격 베이시스 괴리 확대", desc,
                    "선현물 급격한 괴리 — 강제청산/비정상 체결 주의",
                    cooldown_sec=1800 if crit_b else 3600, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_basis_divergence")

            if unauth_pos:
                record_proactive_alert(
                    str(b), "sentinel_unauthorized_position", "CRITICAL",
                    "화이트리스트 외 비인가 종목 보유 감지", ", ".join(str(x) for x in unauth_pos),
                    "비인가 매매·API 키 도용·수동 오조작 여부 즉시 확인 필요",
                    cooldown_sec=1800, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_unauthorized_position")

            if sec_warns:
                record_proactive_alert(
                    str(b), "sentinel_security_alert", "CRITICAL",
                    "계정 보안 / 비거래 자금유출 경보", " | ".join(str(x) for x in sec_warns),
                    "거래소 API 출금권한 및 입출금/이체 내역 즉시 점검 필요",
                    cooldown_sec=1800, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "sentinel_security_alert")

            loops = _track_sentinel_actions(str(b), actions)
            if loops:
                loop_desc = ", ".join(f"{k}({cnt}회/30m)" for k, cnt in loops)
                logger.error(f"[{b}] 🔁 [자가치유 핑퐁 루프 감지] {loop_desc}")
                record_proactive_alert(
                    str(b), "self_heal_loop", "CRITICAL",
                    "자가치유 무한 반복(핑퐁 루프) 감지", loop_desc,
                    "서로 다른 치유/집계 모듈 충돌 가능 — 즉시 점검 필요",
                    cooldown_sec=3600, notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "self_heal_loop")

            if actions:
                logger.warning(f"[{b}] 🛡 센티넬 감사 조치: {', '.join(actions)} (잔고괴리: ${diff:+.4f})")
            else:
                logger.info(f"[{b}] 📋 체결 장부·보호·청산거리 무결성 정상 (잔고괴리: ${diff:+.4f})")
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
        pids = output.strip().split('\n')
        for pid in pids:
            if not pid: continue
            try:
                ps_out = subprocess.check_output(f"ps -p {pid} -o args=", shell=True, text=True)
                if cwd in ps_out:
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
        "-4164", "-4421", "order timeout/error", "최소 주문 단위", "무방비 진입",
        "신호 강도 부족", "증거금 설정 오류", "가용 증거금 부족",
        "name 'cfg' is not defined", "ohlcv 조회 실패", "시황 조회 실패",
        "minimum amount precision", "partial tp 실패",
        "fetch_tickers", "tickers 일괄 조회 실패", "fetch_ohlcv 실패", "nonetype",
        "networkerror", "ratelimitexceeded", "timestamp for this request", "empty dataframe",
        "zerodivisionerror", "-2019", "insufficient balance", "reduceonly", "order failed", "connection reset"
    ]
    now_kst = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=9)
    recent_fails = []
    
    # bot_engine.log를 우선 탐색, 부재 시 bot_stdout.log 확인
    target_logs = [os.path.join(cwd, "bot_engine.log")]
    if not os.path.exists(target_logs[0]):
        target_logs = [os.path.join(cwd, "bot_stdout.log")]
        
    unknown_err_cnt = 0
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
                
                # Timestamp check
                log_dt = None
                try:
                    ts_str = line_str[:19]
                    log_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    diff_sec = abs((now_kst - log_dt).total_seconds())
                    if diff_sec >= 900:
                        continue  # 15분 초과 로그는 무시
                except Exception:
                    pass

                lower_line = line_str.lower()
                # 정상 포스트온리 폴백(-5022) 및 정상 리스크 방어 차단은 장애 카운트에서 제외
                if "-5022" in lower_line or "could not be executed as maker" in lower_line:
                    continue
                if "[risk block]" in lower_line or "[entry block]" in lower_line:
                    if any(ok_blk in lower_line for ok_blk in ("일일 손실 한도", "종목별 쿨다운", "최대 포지션 수", "이미 포지션 보유")):
                        continue

                is_known_err = False
                if any(kw in lower_line for kw in order_err_keywords) or "-4067" in lower_line or "마진모드 설정 실패" in lower_line:
                    recent_fails.append(line_str)
                    seen_lines.add(line_str)
                    is_known_err = True
                
                # 미등록 에러(Unknown Exception) 2중 그물망
                if not is_known_err and ("[error]" in lower_line or "[exception]" in lower_line or "traceback" in lower_line):
                    unknown_err_cnt += 1
                    seen_lines.add(line_str)
        except Exception:
            pass

    # 구조적 주문/모드 거절은 재기동 후에도 재발하므로 60분 누적 추적
    hard_events = []
    for fail_ln in recent_fails:
        fl = fail_ln.lower()
        ts_key = fail_ln[:19]
        if "notional" in fl or "-4164" in fail_ln:
            hard_events.append((ts_key, "NOTIONAL_MIN_ERROR", fail_ln))
        elif "-4067" in fail_ln or "마진모드 설정 실패" in fl:
            hard_events.append((ts_key, "MARGIN_SETTING_ERROR", fail_ln))
        elif "주문 거절" in fl or "order timeout/error" in fl or "주문 결과: none" in fl:
            hard_events.append((ts_key, "ORDER_REJECTED", fail_ln))
    tracked_cnt, tracked_type, tracked_msg = _record_and_count_entry_errors(str(b), hard_events)

    if len(recent_fails) >= 2 or tracked_cnt >= 2:
        last_fail = recent_fails[-1] if recent_fails else tracked_msg
        err_type = tracked_type or "ORDER_REJECTED"
        reason_summary = "주문 반복 거절/실패"
        lower_last = last_fail.lower()
        if "notional" in lower_last or "-4164" in last_fail:
            err_type = "NOTIONAL_MIN_ERROR"
            reason_summary = "최소 주문 명목가치(Notional < 5 USDT) 미달 거절"
        elif "-4067" in last_fail or "마진모드 설정 실패" in lower_last:
            err_type = "MARGIN_SETTING_ERROR"
            reason_summary = "마진모드 설정 거절(-4067)"
        elif "-4421" in last_fail or "leverage" in lower_last:
            err_type = "LEVERAGE_RESTRICTION_ERROR"
            reason_summary = "서브계정 레버리지 제한(5x 초과 불가) 위반"
        elif "cfg' is not defined" in lower_last:
            err_type = "CFG_REFERENCE_ERROR"
            reason_summary = "BTC CONTEXT 등 CFG 객체 참조 실패 (변수 미정의 오류)"
        elif "ohlcv 조회 실패" in lower_last or "시황 조회 실패" in lower_last or "fetch_ohlcv" in lower_last:
            err_type = "TICKER_FETCH_ERROR"
            reason_summary = "시황(OHLCV) 조회 실패"
        elif "fetch_tickers" in lower_last or "tickers 일괄 조회" in lower_last or "nonetype" in lower_last:
            err_type = "TICKER_FETCH_ERROR"
            reason_summary = "스캐너 Tickers API 조회 실패/NoneType 에러 (재기동 생략)"
            # API 일시적 장애이므로 재기동 불필요
            return False, f"단순 시황조회 장애 무시: {reason_summary}", err_type
        elif "minimum amount precision" in lower_last or "partial tp 실패" in lower_last:
            err_type = "PARTIAL_TP_PRECISION_ERROR"
            reason_summary = "최소 주문수량(precision) 미달로 인한 주문/부분청산 실패"
        elif "증거금 설정 오류" in last_fail:
            err_type = "MARGIN_SETTING_ERROR"
            reason_summary = "증거금 하한선 미달에 의한 진입 차단"
        elif "신호 강도 부족" in last_fail:
            err_type = "STRENGTH_GATE_MISMATCH"
            reason_summary = "전략 시그널 강도와 리스크 게이트(required_strength) 불일치 차단"
        elif "가용 증거금 부족" in last_fail:
            err_type = "AVAILABLE_MARGIN_ERROR"
            reason_summary = "요구 증거금이 가용 잔고를 초과하여 진입 차단"
        elif "insufficient" in lower_last or "-2019" in last_fail or "잔고" in last_fail:
            err_type = "INSUFFICIENT_FUNDS"
            reason_summary = "증거금/잔고 부족 거절"
        elif "timeout" in lower_last or "networkerror" in lower_last or "connection reset" in lower_last:
            err_type = "API_TIMEOUT_ERROR"
            reason_summary = "거래소 네트워크/API 타임아웃 장애"
        elif "ratelimit" in lower_last:
            err_type = "API_RATELIMIT_ERROR"
            reason_summary = "거래소 API RateLimit 초과 (밴 위험)"
            
        return True, f"진입 주문 장애 감지 ({len(recent_fails)}회 발생: {reason_summary})", err_type
        
    if unknown_err_cnt >= 5:
        return True, f"미등록 치명적 예외(Unknown Error) 다수 감지 ({unknown_err_cnt}회)", "UNKNOWN_FATAL_ERROR"
        
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
            today_kst = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=9)).strftime("%Y-%m-%d")
            s_date = sdata.get("consec_sl_date", "")
            is_halted = sdata.get("halted_by_consec_sl", False)
            if is_halted and s_date and s_date < today_kst:
                return True, f"전일({s_date}) 연속손절 정지 락 잔존 데드락"
        except Exception:
            pass

    # 3) 최근 엔진 로그 trader disabled 발생 검사 (최근 15분 이내)
    now_kst = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=9)
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
    # bot.py의 FileHandler가 직접 기록하는 bot_engine.log를 최우선으로 보고,
    # 복수 로그 중 가장 최근 갱신된 파일 기준으로 정체 여부를 판정해 오탐 재기동을 방지한다.
    log_mtimes = []
    for log_name in ["bot_engine.log", "bot_stdout.log"]:
        log_path = os.path.join(cwd, log_name)
        if os.path.exists(log_path):
            try:
                log_mtimes.append(os.path.getmtime(log_path))
            except Exception:
                pass
    if log_mtimes:
        elapsed = time.time() - max(log_mtimes)
        if elapsed > 900:
            return True, f"스캐너 루프 정체(Stall: {int(elapsed/60)}분간 로그 갱신 없음)"

    # 5) 화이트리스트 스캔 누락(Whitelist Scan Drop) 검사
    sr_file = os.path.join(cwd, "scan_results.json")
    if os.path.exists(cfg_file) and os.path.exists(sr_file):
        try:
            if (time.time() - os.path.getmtime(sr_file)) < 600:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    cfg_w = json.load(f)
                with open(sr_file, "r", encoding="utf-8") as f:
                    sr_w = json.load(f)
                wl = cfg_w.get("SYMBOL_WHITELIST", []) or []
                ex_id = str(cfg_w.get("EXCHANGE_ID", "okx")).lower()
                if ex_id == "binance":
                    wl = [s for s in wl if s not in ("OKB/USDT:USDT", "PEPE/USDT:USDT")]
                res_list = sr_w.get("results", sr_w) if isinstance(sr_w, dict) else sr_w
                if wl and isinstance(res_list, list) and len(res_list) < len(wl) - 1:
                    return True, f"화이트리스트 스캔 누락 감지 ({len(res_list)}/{len(wl)}개만 스캔됨)"
        except Exception:
            pass

    return False, "무포지션 대기 중 정상 (정상 스캔 지속)"

def run_entry_recovery_global():
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entry_recovery.py")
    if os.path.exists(script):
        subprocess.run(["python3", script], capture_output=True)

def check_and_fix_bot(b: int, do_config_check: bool = True, do_flat_check: bool = False, do_audit_33: bool = False):
    cwd = f"/Users/l/project/{b}"
    if not os.path.exists(cwd):
        logger.warning(f"[{b}] 봇 폴더가 존재하지 않습니다.")
        return
        
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return
        
    needs_restart = False
    allow_hot_restart_with_pos = False
    action_taken = []
    
    # [결함#3 수정 / 원칙 준수] AUTO_TRADING=False 감지 시 config.json 임의 덮어쓰기 차단 → 경보 전용 전환
    cfg_file = os.path.join(cwd, "config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if not cfg.get("AUTO_TRADING", True):
                logger.warning(f"[{b}] 🚨 AUTO_TRADING=False 감지 (자동매매 꺼짐) — config.json 임의 수정 차단, 긴급 경보 발송")
                record_proactive_alert(
                    str(b),
                    "auto_trading_off",
                    "CRITICAL",
                    "자동매매 스위치 OFF 감지",
                    "config.json AUTO_TRADING=False 상태 (신규 진입 중단)",
                    "보스 의도적 OFF가 아니라면 UI 또는 승인 후 ON 전환 검토 필요",
                    cooldown_sec=7200,
                    notify_discord=True,
                )
            else:
                clear_proactive_alert(str(b), "auto_trading_off")
        except Exception as e:
            logger.error(f"[{b}] ⚠️ AUTO_TRADING 상태 점검 중 오류: {e}")
    
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

    # 1-0. [AI 10대 자율감사 모듈 1·6] 코드-메모리 미반영(Stale Code) + 중복프로세스/로그FD 단절 상시 검사
    if bot_alive and not needs_restart:
        try:
            stale_code, stale_reason = check_stale_code_sync(b, cwd)
            if stale_code:
                maint_on, maint_desc = is_maintenance_active()
                if maint_on:
                    logger.info(f"[{b}] 🛠️ [정비 윈도우 활성] {stale_reason} → M1 자동 핫리로드 유예 ({maint_desc})")
                else:
                    logger.warning(f"[{b}] 🔄 [AI 자율감사 M1] {stale_reason} → 포지션 보존 안전 핫리로드 트리거")
                    needs_restart = True
                    allow_hot_restart_with_pos = True
                    action_taken.append(stale_reason)
            fd_issue, fd_reason, fd_restart = check_log_fd_and_pid_lock_integrity(b, cwd)
            if fd_issue and fd_restart:
                logger.warning(f"[{b}] 🔄 [AI 자율감사 M6] {fd_reason}")
                needs_restart = True
                allow_hot_restart_with_pos = True
                action_taken.append(fd_reason)
            elif "동기화" in fd_reason:
                logger.info(f"[{b}] 🛠 [AI 자율감사 M6] {fd_reason}")
        except Exception as e:
            logger.debug(f"[{b}] 상시 M1/M6 감사 예외: {e}")
        
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

                # [원칙 준수] config.json / 리스크 파라미터 임의 자동 수정 금지 -> 선제 진단·승인 권고 보고만 기록
                if err_type in ("NOTIONAL_MIN_ERROR", "LEVERAGE_RESTRICTION_ERROR", "MARGIN_SETTING_ERROR", "AVAILABLE_MARGIN_ERROR", "STRENGTH_GATE_MISMATCH"):
                    cfg_file = os.path.join(cwd, "config.json")
                    cur_margin = cur_lev = cur_risk = None
                    if os.path.exists(cfg_file):
                        try:
                            with open(cfg_file, "r", encoding="utf-8") as cf:
                                b_cfg = json.load(cf)
                            cur_lev = float(b_cfg.get("LEVERAGE", 3.0) or 3.0)
                            cur_margin = float(b_cfg.get("MARGIN_USDT", 1.5) or 1.5)
                            cur_risk = float(b_cfg.get("RISK_PER_TRADE_PCT", 0.01) or 0.01)
                        except Exception:
                            pass
                    if err_type == "STRENGTH_GATE_MISMATCH":
                        rec = "strategy.py 시그널 강도와 trader.py _risk_check required_strength 게이트 불일치 — 코드/게이트 정합화 점검 권고"
                    else:
                        rec = (
                            f"{err_type} 반복 발생 (margin={cur_margin}, lev={cur_lev}, risk={cur_risk}) — "
                            "보스 승인 후 최소 주문금액(>=5 USDT 명목가) 또는 증거금/리스크 한도 점검 권고"
                        )
                    logger.warning(f"[{b}] 📋 자동 설정 변경 차단됨 (승인 대기 보고): {rec}")
                    sev = "CRITICAL" if err_type in ("NOTIONAL_MIN_ERROR", "MARGIN_SETTING_ERROR", "ORDER_REJECTED") else "WARN"
                    record_proactive_alert(
                        str(b),
                        f"entry_{err_type.lower()}",
                        sev,
                        f"진입 주문 이상 감지 ({err_type})",
                        entry_reason,
                        rec,
                        cooldown_sec=3600,
                        notify_discord=True,
                    )
                    action_taken.append("설정 자동변경 차단·보고완료")

                needs_restart = err_type not in (
                    "AVAILABLE_MARGIN_ERROR",
                    "INSUFFICIENT_BALANCE_ERROR",
                    "STRENGTH_GATE_MISMATCH",
                    "NOTIONAL_MIN_ERROR",
                    "LEVERAGE_RESTRICTION_ERROR",
                    "MARGIN_SETTING_ERROR",
                )
            else:
                for clr_k in (
                    "entry_notional_min_error",
                    "entry_leverage_restriction_error",
                    "entry_margin_setting_error",
                    "entry_available_margin_error",
                    "entry_strength_gate_mismatch",
                    "entry_order_rejected",
                ):
                    clear_proactive_alert(str(b), clr_k)
                # 2) 무포지션 봇 정밀 건전성 감사
                flat_issue, flat_reason = check_flat_bot_readiness(b, cwd)
                if flat_issue:
                    logger.warning(f"[{b}] 🚨 무포지션 건전성 이상 감지: {flat_reason}")
                    needs_restart = True
                    action_taken.append(flat_reason)
                else:
                    logger.info(f"[{b}] 🛡 무포지션 건전성: {flat_reason}")

            # 3) [AI 12대 자율감사] 전 파이프라인(모듈 2/3/4/6/7/8/9/10/11/12) 통합 감시·자가치유
            audit_res = run_all_autonomous_audits(b, cwd)
            if audit_res["healed"]:
                logger.warning(f"[{b}] 🛠 [AI 10대 자율감사] 자가 치유 수행: {' | '.join(audit_res['healed'])}")
            active_ai_keys = {k for k, _ in audit_res["issues"]}
            for ai_k in (
                "ai_unexecuted_signal_trace",
                "ai_sizing_preflight",
                "ai_signal_gate_contract",
                "ai_log_fd_pid_lock",
                "ai_cooldown_reentry",
                "ai_scan_indicator_health",
                "ai_7zone_sync",
                "ai_position_context",
                "ai_ledger_seq_integrity",
                "ai_self_heal_loop",
                "ai_rapid_self_destruct",
                "ai_engine_states_pollution",
            ):
                if ai_k not in active_ai_keys:
                    clear_proactive_alert(str(b), ai_k)
            if audit_res["issues"]:
                issue_msgs = [msg for _, msg in audit_res["issues"]]
                logger.warning(f"[{b}] 🚨 [AI 10대 자율감사] 이상 감지: {' | '.join(issue_msgs)}")
                for key, msg in audit_res["issues"]:
                    is_crit = key in ("ai_self_heal_loop", "ai_rapid_self_destruct", "ai_engine_states_pollution")
                    ai_sev = "CRITICAL" if is_crit else "WARN"
                    record_proactive_alert(
                        str(b),
                        key,
                        ai_sev,
                        "AI 자율감사 이상 감지" if not is_crit else "AI 선제 자폭/오염 긴급 경보",
                        msg,
                        "원인 분석 및 조치 결과 확인 필요",
                        cooldown_sec=3600 if is_crit else 21600,
                        notify_discord=True,
                    )
                if audit_res["needs_restart"]:
                    needs_restart = True
                    action_taken.extend(issue_msgs)
            else:
                if audit_res["needs_restart"]:
                    needs_restart = True
                    action_taken.extend(audit_res["healed"])
                logger.info(
                    f"[{b}] 🤖 [AI 10대 자율감사] 14/14 전수 정상 "
                    f"({audit_res['gate_summary']} | {audit_res['scan_summary']})"
                )
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
                    if allow_hot_restart_with_pos:
                        logger.warning(f"[{b}] 🔄 [AI 자율감사] 디스크 코드 변경 반영을 위해 보유 포지션({len(pdata)}건) 상태 보존 핫리로드 허용")
                    else:
                        logger.warning(f"[{b}] 🛡 포지션({len(pdata)}건) 보유 확인! 트레일링 스탑 보호를 위해 재기동 유예.")
                        needs_restart = False
        except Exception as e:
            logger.error(f"[{b}] ⚠️ 포지션 상태 확인 실패: {e}")

    # [보스 지침] 이상이 감지되었으나 포지션 보호로 재기동이 유예된 경우 텔레그램 경보 발송
    if action_taken and not needs_restart and bot_alive:
        try:
            alert_msg = f"⚠️ **[워치독 진입 이상 감지 (재기동 유예): {b}]**\\n\\n감지 내역: {', '.join(action_taken)}\\n상태: 포지션 보호를 위해 재기동 유예 (설정 자동변경 차단 · 승인 대기 보고 완료)."
            py_cmd = f"import sys; sys.path.insert(0, '{cwd}'); import core.alert as alert; alert.send_telegram_alert('{alert_msg}')"
            subprocess.run(["python3", "-c", py_cmd], cwd=cwd)
        except Exception as e:
            logger.error(f"[{b}] 텔레그램 알림 발송 실패: {e}")

    # 3. 조치 (재기동)
    if needs_restart:
        r_joined = " ".join(action_taken)
        is_proc_or_cpu = (not bot_alive) or ("CPU" in r_joined) or ("M1" in r_joined) or ("코드 수정" in r_joined)
        net_down, net_desc = is_external_network_down()
        if net_down and not is_proc_or_cpu:
            logger.warning(f"[{b}] 🌐 [M33 망 단절 실드] 외부망 단절로 재기동 보류 ({net_desc} | 사유: {r_joined[:100]})")
            return

        logger.info(f"[{b}] 🛠 공유 락(flock) 기반 2-Step 안전 재부팅 시도...")

        restart_ok, restart_detail = bot_restart_locked(
            str(b), cwd, source="watchdog_entry", reason=", ".join(action_taken) or "health_restart", cooldown_sec=120
        )
        if not restart_ok:
            logger.info(f"[{b}] ⏭️ 재기동 생략/보류 ({restart_detail})")
        else:
            logger.info(f"[{b}] ✅ 재기동 완료. 조치 내역: {', '.join(action_taken)} ({restart_detail})")
            time.sleep(5)
            try:
                alert_msg = f"🚨 **[워치독 긴급 조치: {b}]**\\n\\n발견된 문제: {', '.join(action_taken)}\\n조치: 공유 락 2-Step Graceful 재기동 완료."
                py_cmd = f"import sys; sys.path.insert(0, '{cwd}'); import core.alert as alert; alert.send_telegram_alert('{alert_msg}')"
                subprocess.run(["python3", "-c", py_cmd], cwd=cwd, timeout=15)
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

_AEGIS_DOMAIN_PREFIXES = (
    "infra_", "portfolio_", "tca_", "alpha_", "market_regime_",
    "blackswan_", "security_", "feed_", "host_", "canary_", "otr_",
)


def _sync_aegis_alerts(alerts: list) -> None:
    """Sync M16~M34 global/per-bot alerts and auto-clear any previously active resolved keys."""
    detected = set()
    for a in (alerts or []):
        bid = str(a.get("bot_id") or "8888")
        akey = str(a.get("key") or "")
        if not akey:
            continue
        detected.add((bid, akey))
        sev = str(a.get("severity") or "WARN").upper()
        cd = 1800 if sev == "CRITICAL" else 14400
        record_proactive_alert(
            bid,
            akey,
            sev,
            str(a.get("title") or akey),
            str(a.get("details") or ""),
            str(a.get("recommendation") or ""),
            cooldown_sec=cd,
            notify_discord=True,
        )

    try:
        active = (load_proactive_alerts().get("active") or {})
        for k, entry in list(active.items()):
            bid = str((entry or {}).get("bot_id") or "")
            akey = str((entry or {}).get("alert_key") or "")
            # Preserve event-based host_mac_sleep_wake alert once emitted until cooldown/manual clear or next sleep check
            if akey == "host_mac_sleep_wake":
                continue
            if akey.startswith(_AEGIS_DOMAIN_PREFIXES) and (bid, akey) not in detected:
                clear_proactive_alert(bid, akey)
    except Exception:
        pass


def _run_aegis_v7_global_audit(cycle: int) -> None:
    """Execute Aegis V7 global modules (M16~M34): Security/Ops + Exchange/Infra + Portfolio/OTR/Alpha/Scorecard."""
    include_listings = (cycle == 1) or (cycle % 15 == 0)
    include_canary = (cycle == 1) or (cycle % 60 == 0)

    try:
        sec_res = run_security_ops_audit(BOT_LIST, include_canary=include_canary)
    except Exception as e:
        logger.error(f"🚨 [Aegis V7 Security/Ops] 감사 예외: {e}")
        sec_res = {"alerts": [], "summary": {}}

    try:
        infra_res = run_exchange_infra_audit(BOT_LIST, include_listings=include_listings)
    except Exception as e:
        logger.error(f"🚨 [Aegis V7 Infra] 감사 예외: {e}")
        infra_res = {"alerts": [], "summary": {}}

    try:
        port_res = run_portfolio_risk_audit(
            BOT_LIST,
            infra_summary=infra_res.get("summary"),
            send_daily_briefing=True,
        )
    except Exception as e:
        logger.error(f"🚨 [Aegis V7 Portfolio] 감사 예외: {e}")
        port_res = {"alerts": [], "scorecard": {}}

    combined_alerts = (
        (sec_res.get("alerts") or [])
        + (infra_res.get("alerts") or [])
        + (port_res.get("alerts") or [])
    )
    _sync_aegis_alerts(combined_alerts)

    sc = port_res.get("scorecard") or {}
    m16 = ((port_res.get("summary") or {}).get("m16_exposure") or {})
    m24 = ((infra_res.get("summary") or {}).get("m24_host_resources") or {})
    m28 = ((sec_res.get("summary") or {}).get("m28_usdt_peg") or {})
    m33 = ((sec_res.get("summary") or {}).get("m33_host_ops") or {})
    rot = m24.get("rotated_logs") or []
    rot_txt = f" | 로그로테이션:{','.join(rot)}" if rot else ""
    usdt_txt = f"${m28['usdt_usd_avg']:.4f}" if m28.get("usdt_usd_avg") else "N/A"
    logger.info(
        f"🛡️ [Aegis V7 종합점검] 스코어 {sc.get('score', '?')}/100 ({sc.get('grade', '?')}) | "
        f"노출 ${m16.get('gross_notional', 0):.2f} (Net ${m16.get('net_notional', 0):+.2f}, {m16.get('total_positions', 0)}포) | "
        f"USDT {usdt_txt} | IP {m33.get('public_ip', '?')} | 신규경보 {len(combined_alerts)}건 | 디스크 {m24.get('disk_used_pct', '?')}%{rot_txt}"
    )


def main():
    logger.info("==========================================")
    logger.info("🐶 Watchdog System Started (Aegis V7 Full Suite + Profitability Guard Active)")
    logger.info("==========================================")
    cycle = 0
    while True:
        cycle += 1
        try:
            update_watchdog_heartbeat("watchdog_entry", {"cycle": cycle, "phase": "start"})
        except Exception:
            pass
        do_config_check = (cycle % CONFIG_CHECK_CYCLES == 1) or (CONFIG_CHECK_CYCLES == 1)
        do_flat_check = (cycle % FLAT_BOT_CHECK_CYCLES == 0) or (cycle == 1)
        do_audit_33 = (cycle % AUDIT_33_CYCLES == 0)
        if do_flat_check:
            try:
                pruned_cnt = prune_expired_proactive_alerts(7200)
                if pruned_cnt > 0:
                    logger.info(f"🧹 [Auto-Clear] 만료된 repeat_restart/structural 경보 {pruned_cnt}건 자동 해제")
            except Exception as pe:
                logger.debug(f"만료 경보 자동 해제 예외: {pe}")
        
        run_entry_recovery_global()

        logger.info(f"--- 순찰 사이클 {cycle} 시작 (Config 검증: {do_config_check}, 무포지션 감사: {do_flat_check}, 33대 감사: {do_audit_33}) ---")
        for bot in BOT_LIST:
            try:
                check_and_fix_bot(bot, do_config_check=do_config_check, do_flat_check=do_flat_check, do_audit_33=do_audit_33)
            except Exception as e:
                logger.error(f"[{bot}] 워치독 순찰 중 치명적 오류: {e}")

        if do_flat_check:
            _run_aegis_v7_global_audit(cycle)

        try:
            update_watchdog_heartbeat("watchdog_entry", {"cycle": cycle, "phase": "done"})
        except Exception:
            pass
        logger.info(f"순찰 완료. {HEALTH_CHECK_SEC}초 후 다음 순찰 진행...")
        sleep_t0 = time.time()
        time.sleep(HEALTH_CHECK_SEC)
        elapsed = time.time() - sleep_t0
        if elapsed > HEALTH_CHECK_SEC + 180:
            logger.warning(f"🚨 [M33 Mac 절전/깨어남 감지] sleep({HEALTH_CHECK_SEC}s) 실제 경과 {elapsed:.0f}s")
            record_proactive_alert(
                "8888",
                "host_mac_sleep_wake",
                "WARN",
                f"Mac 절전/중단 후 복귀 감지 ({elapsed:.0f}초 멈춤)",
                f"예정 {HEALTH_CHECK_SEC}초 대기 중 {elapsed:.0f}초 경과 — 잠자기 또는 일시 정지 의심",
                "macOS 전원/잠자기 설정 및 9개 봇 상태 확인 권고",
                cooldown_sec=3600,
                notify_discord=True,
            )
        elif do_flat_check:
            clear_proactive_alert("8888", "host_mac_sleep_wake")

if __name__ == "__main__":
    main()
