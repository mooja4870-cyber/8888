#!/usr/bin/env python3
"""
autonomous_auditor.py — 8888 10대 AI 자율 발굴·자가 치유 감사 엔진

매매 전 파이프라인(코드 동기화 → 시그널 추적 → 사이징 프리플라이트 → 게이트 계약 →
프로세스/로그FD 무결성 → 쿨다운/재진입 정합성 → 스캔/지표 건전성 → 7대영역 동기화 →
포지션 보호 컨텍스트 복원)을 상시 자동 감사하여 조용한 매매 저해 요인을 선제 치유한다.
(모듈 5 및 거래소 고아 알고주문 청소는 bot_sentinel.py와 연계 수행)
"""
import ast
import csv
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple


def _now_kst() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=9)


def _load_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _atomic_write_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _atomic_write_text(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _get_lock_pid(bot_id: int, cwd: str) -> Optional[int]:
    for path in (f"/tmp/quantum_{bot_id}_trader.lock", os.path.join(cwd, "bot.pid")):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if raw.isdigit():
                pid = int(raw)
                if subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode == 0:
                    return pid
        except Exception:
            continue
    return None


def _get_process_start_epoch(pid: int) -> Optional[float]:
    try:
        res = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True, timeout=3)
        raw = " ".join((res.stdout or "").strip().split())
        return datetime.strptime(raw, "%a %b %d %H:%M:%S %Y").timestamp() if raw else None
    except Exception:
        return None


# ── [모듈 1] 디스크 코드 변경 후 메모리 미반영(Stale Code) 감사 ──────────────
def check_stale_code_sync(bot_id: int, cwd: str) -> Tuple[bool, str]:
    """실행 중인 bot.py 기동 시각과 디스크 .py 수정 시각을 대조해 미반영 상태를 탐지한다."""
    pid = _get_lock_pid(bot_id, cwd)
    if pid is None:
        return False, "실행 PID 없음"
    proc_start_ts = _get_process_start_epoch(pid)
    if proc_start_ts is None:
        return False, "기동 시각 조회 불가"

    watch_files: List[str] = []
    bot_py = os.path.join(cwd, "bot.py")
    if os.path.exists(bot_py):
        watch_files.append(bot_py)
    core_dir = os.path.join(cwd, "core")
    if os.path.isdir(core_dir):
        watch_files.extend(os.path.join(core_dir, fn) for fn in os.listdir(core_dir) if fn.endswith(".py"))

    now_ts = time.time()
    newer = []
    for fp in watch_files:
        try:
            mt = os.path.getmtime(fp)
            if mt > proc_start_ts + 30.0 and (now_ts - mt) > 15.0:
                newer.append(os.path.relpath(fp, cwd))
        except OSError:
            continue
    if newer:
        sample = ", ".join(sorted(newer)[:3])
        extra = f" 외 {len(newer) - 3}건" if len(newer) > 3 else ""
        return True, f"디스크 코드 수정 후 미재기동 감지 ({sample}{extra})"
    return False, "코드-메모리 동기화 정상"


# ── [모듈 2] 무포지션 시그널 미체결 역추적 및 스테일 락 자동 해제 ─────────────
def check_unexecuted_signal_trace(bot_id: int, cwd: str) -> Tuple[bool, str, bool]:
    """만료된 recently_entered 락 청소 및 최근 30분 시그널 차단 원인을 추적한다."""
    pos_data = _load_json(os.path.join(cwd, "data", "active_positions.json"), {})
    if isinstance(pos_data, dict) and pos_data:
        return False, "보유 포지션 있음", False

    eng_state_file = os.path.join(cwd, "data", "engine_states.json")
    estate = _load_json(eng_state_file)
    if isinstance(estate, dict):
        rec = estate.get("recently_entered") or {}
        if isinstance(rec, dict) and rec:
            now_local = datetime.now()
            kept, stale = {}, []
            for sym, ts_str in rec.items():
                try:
                    dt = datetime.fromisoformat(str(ts_str).split("+")[0])
                    if (now_local - dt).total_seconds() <= 600:
                        kept[sym] = ts_str
                    else:
                        stale.append(sym)
                except Exception:
                    stale.append(sym)
            if stale:
                estate["recently_entered"] = kept
                _atomic_write_json(eng_state_file, estate)
                return True, f"만료된 recently_entered 락 자동 해제 ({', '.join(stale)})", True

    log_path = os.path.join(cwd, "bot_engine.log")
    if not os.path.exists(log_path):
        log_path = os.path.join(cwd, "bot_stdout.log")
    if not os.path.exists(log_path):
        return False, "미체결 차단 이상 없음", False

    try:
        with open(log_path, "rb") as lf:
            lf.seek(0, os.SEEK_END)
            lf.seek(max(0, lf.tell() - 32768))
            tail = lf.read().decode("utf-8", errors="ignore")
    except Exception:
        return False, "미체결 차단 이상 없음", False

    now_kst = _now_kst()
    sigs, blocks = [], []
    for line in tail.splitlines():
        ls = line.strip()
        if len(ls) < 19:
            continue
        try:
            ldt = datetime.strptime(ls[:19], "%Y-%m-%d %H:%M:%S")
            if abs((now_kst - ldt).total_seconds()) > 1800:
                continue
        except Exception:
            continue
        low = ls.lower()
        if any(t in low for t in ("[sig]", "[signal]", "[fusion signal]", "[donchian signal]")):
            sigs.append(ls)
        if any(t in low for t in ("trader disabled", "신호 강도 부족", "최소 주문 단위", "minimum amount precision", "[entry block]", "[risk block]")):
            blocks.append(ls)

    if sigs and blocks:
        last_b = blocks[-1]
        if "trader disabled" in last_b.lower():
            return True, f"최근 시그널 후 trader disabled 차단 ({last_b[:80]})", True
        if any(k in last_b.lower() for k in ("신호 강도 부족", "최소 주문 단위", "minimum amount precision")):
            return True, f"최근 시그널 게이트/수량 차단 ({last_b[:100]})", False
    return False, "미체결 차단 이상 없음", False


# ── [모듈 3] 주문 수량·최소 단위 프리플라이트 감사 ───────────────────────────
def check_order_sizing_preflight(bot_id: int, cwd: str) -> Tuple[bool, str]:
    """exchange.py 최소수량 자동 보정 가드 및 증거금/레버리지 설정 유효성을 점검한다."""
    ex_path = os.path.join(cwd, "core", "exchange.py")
    cfg = _load_json(os.path.join(cwd, "config.json"))
    if not (os.path.exists(ex_path) and isinstance(cfg, dict)):
        return False, "설정/거래소 모듈 없음"

    try:
        with open(ex_path, "r", encoding="utf-8") as f:
            if "[MIN AMOUNT ADJUST]" not in f.read():
                return True, "exchange.py 최소 주문 수량 자동 보정([MIN AMOUNT ADJUST]) 가드 누락"
        margin_usdt = float(cfg.get("MARGIN_USDT", 0.0) or 0.0)
        eq_scale = float(cfg.get("EQUITY_SCALE_FACTOR", 1.0) or 1.0)
        lev = float(cfg.get("LEVERAGE", 3.0) or 3.0)
        if not cfg.get("USE_AUTO_COMPOUND", False) and float(cfg.get("RISK_PER_TRADE_PCT", 0.0) or 0.0) <= 0:
            if margin_usdt * eq_scale < 1.0:
                return True, f"고정 증거금 설정 과소 ({margin_usdt * eq_scale:.2f} USDT < 1.0 USDT)"
        if lev <= 0:
            return True, f"레버리지 설정 오류 ({lev})"
    except Exception as e:
        return False, f"프리플라이트 스킵 ({e})"
    return False, "주문 사이징 프리플라이트 정상"


# ── [모듈 4] AST 기반 시그널 강도 ↔ 리스크 게이트 계약 감사 ─────────────────
def _parse_strategy_outputs(strat_path: str) -> Tuple[Set[str], int]:
    with open(strat_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=strat_path)
    consts = {
        node.targets[0].id: node.value.value
        for node in getattr(tree, "body", [])
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    default_type: Optional[str] = None
    emitted: Set[str] = set()
    strengths: List[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Signal":
            for st in node.body:
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.target.id == "strategy_type":
                    if isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                        default_type = st.value.value
                    elif isinstance(st.value, ast.Name) and st.value.id in consts:
                        default_type = consts[st.value.id]
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "strategy_type" and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    emitted.add(node.value.value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Signal":
            kw_map = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            is_none_kw = isinstance(kw_map.get("direction"), ast.Constant) and kw_map["direction"].value == "none"
            is_none_arg = len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == "none"
            if is_none_kw or is_none_arg:
                continue
            stv = kw_map.get("strategy_type")
            if isinstance(stv, ast.Constant) and isinstance(stv.value, str):
                emitted.add(stv.value)
            elif isinstance(stv, ast.Name) and stv.id in consts:
                emitted.add(consts[stv.id])
            s_expr = kw_map.get("strength") or (node.args[2] if len(node.args) >= 3 else None)
            if isinstance(s_expr, ast.Constant) and isinstance(s_expr.value, (int, float)) and s_expr.value > 0:
                strengths.append(int(s_expr.value))
            elif isinstance(s_expr, ast.IfExp) and isinstance(s_expr.body, ast.Constant) and isinstance(s_expr.body.value, (int, float)) and s_expr.body.value > 0:
                strengths.append(int(s_expr.body.value))

    if not emitted and default_type:
        emitted.add(default_type)
    return emitted, (min(strengths) if strengths else 100)


def _collect_if_chain(if_node: ast.If, gate_map: Dict[str, int], default_box: List[int]) -> None:
    keys: List[str] = []
    for n in ast.walk(if_node.test):
        if isinstance(n, ast.Compare):
            for c in n.comparators:
                for sub in ast.walk(c):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value:
                        keys.append(sub.value)
    for st in if_node.body:
        if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "required_strength" for t in st.targets):
            if isinstance(st.value, ast.Constant) and isinstance(st.value.value, (int, float)):
                for k in dict.fromkeys(keys):
                    gate_map[k] = int(st.value.value)
    if if_node.orelse:
        if len(if_node.orelse) == 1 and isinstance(if_node.orelse[0], ast.If):
            _collect_if_chain(if_node.orelse[0], gate_map, default_box)
        else:
            for st in if_node.orelse:
                if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "required_strength" for t in st.targets):
                    if isinstance(st.value, ast.Constant) and isinstance(st.value.value, (int, float)):
                        default_box[0] = int(st.value.value)


def check_signal_gate_contract(bot_id: int, cwd: str) -> Tuple[bool, str]:
    """strategy.py 활성 시그널 강도와 trader.py _risk_check() required_strength 정합성을 검사한다."""
    strat_path = os.path.join(cwd, "core", "strategy.py")
    trader_path = os.path.join(cwd, "core", "trader.py")
    if not (os.path.exists(strat_path) and os.path.exists(trader_path)):
        return False, "전략/트레이더 파일 없음"
    try:
        emitted, min_str = _parse_strategy_outputs(strat_path)
        with open(trader_path, "r", encoding="utf-8") as f:
            ttree = ast.parse(f.read(), filename=trader_path)
        gate_map: Dict[str, int] = {}
        default_box = [90]
        for node in ast.walk(ttree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "_risk_check":
                for st in node.body:
                    if isinstance(st, ast.If) and "required_strength" in ast.dump(st):
                        _collect_if_chain(st, gate_map, default_box)
    except Exception as e:
        return False, f"시그널-게이트 정적 분석 스킵 ({e})"

    if not emitted:
        return False, "활성 시그널 유형 추출 불가"
    bad = [f"{st}: 생성 {min_str}% < 필요 {gate_map.get(st, default_box[0])}%" for st in sorted(emitted) if min_str < gate_map.get(st, default_box[0])]
    if bad:
        return True, f"시그널-게이트 불일치 ({'; '.join(bad)})"
    return False, f"시그널-게이트 정상 ({','.join(sorted(emitted))}≥{min_str}%)"


# ── [모듈 6] 중복 프로세스 · PID/Lock 동기화 · 로그 FD 단절 감시 ───────────
def check_log_fd_and_pid_lock_integrity(bot_id: int, cwd: str) -> Tuple[bool, str, bool]:
    """중복 bot.py 실행, lock↔bot.pid 불일치(자동 동기화), bot_engine.log FD 단절을 탐지한다."""
    lock_file = f"/tmp/quantum_{bot_id}_trader.lock"
    pid_file = os.path.join(cwd, "bot.pid")
    bot_py = os.path.join(cwd, "bot.py")

    # 1) 동일 폴더 bot.py 중복 실행 검사
    live_pids: List[int] = []
    try:
        out = subprocess.check_output(["ps", "-eo", "pid=,args="], text=True, timeout=3)
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].isdigit() and bot_py in parts[1]:
                live_pids.append(int(parts[0]))
    except Exception:
        pass
    if len(live_pids) > 1:
        return True, f"중복 bot.py 프로세스 감지 ({live_pids}) — 이중 매매 차단 필요", True

    # 2) lock 파일 PID ↔ bot.pid 자동 동기화
    healed_msg = ""
    lock_pid = None
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if raw.isdigit() and subprocess.run(["kill", "-0", raw], capture_output=True).returncode == 0:
                lock_pid = int(raw)
        except Exception:
            pass
    if lock_pid is not None:
        cur_pid_raw = ""
        if os.path.exists(pid_file):
            try:
                cur_pid_raw = open(pid_file, "r", encoding="utf-8").read().strip()
            except Exception:
                pass
        if cur_pid_raw != str(lock_pid):
            try:
                _atomic_write_text(pid_file, f"{lock_pid}\n")
                healed_msg = f"bot.pid 자동 동기화 ({cur_pid_raw or '없음'}→{lock_pid})"
            except Exception:
                pass

    # 3) 로그 로테이션 FD 단절(.bak 쓰기) 감지
    check_pid = lock_pid or (live_pids[0] if live_pids else None)
    if check_pid is not None:
        try:
            lsof_out = subprocess.check_output(["lsof", "-p", str(check_pid), "-Fn"], text=True, timeout=3)
            paths = [ln[1:] for ln in lsof_out.splitlines() if ln.startswith("n")]
            bak_log = os.path.join(cwd, "bot_engine.log.bak")
            main_log = os.path.join(cwd, "bot_engine.log")
            if bak_log in paths and main_log not in paths:
                return True, f"엔진 로그 FD 단절 감지 (PID {check_pid}가 .bak에 기록 중) → 재기동 복구", True
        except Exception:
            pass

    if healed_msg:
        return False, healed_msg, False
    return False, "프로세스/FD/PID 무결성 정상", False


# ── [모듈 7] 쿨다운 · 손절 한정 재진입 차단 정합성 자동 감사/청소 ──────────
def check_cooldown_and_reentry_integrity(bot_id: int, cwd: str) -> Tuple[bool, str, bool]:
    """만료 쿨다운 청소, 익절 후 오작동 심볼 쿨다운 자동 해제, engine.py 가드를 점검한다."""
    stats_file = os.path.join(cwd, "data", "stats.json")
    stats = _load_json(stats_file)
    if not isinstance(stats, dict):
        return False, "stats.json 없음", False

    now = datetime.now()
    changed = False
    healed: List[str] = []

    g_cd = stats.get("global_cooldown_until")
    if g_cd:
        try:
            if datetime.fromisoformat(str(g_cd).split("+")[0]) <= now:
                stats["global_cooldown_until"] = None
                changed = True
                healed.append("만료 글로벌 쿨다운 해제")
        except Exception:
            stats["global_cooldown_until"] = None
            changed = True

    s_cd = stats.get("symbol_cooldown_until")
    if isinstance(s_cd, dict) and s_cd:
        # 최근 종목별 청산 손익 확인 (익절 청산인데 장기 쿨다운 걸린 경우 해제)
        last_exit_pnl: Dict[str, float] = {}
        csv_file = os.path.join(cwd, "data", "trade_history.csv")
        if os.path.exists(csv_file):
            try:
                with open(csv_file, "r", encoding="utf-8-sig") as cf:
                    for row in csv.DictReader(cf):
                        kind = row.get("유형") or row.get("category") or ""
                        if "청산" in kind:
                            sym = row.get("심볼") or row.get("symbol") or ""
                            pnl_val = float(row.get("수익(USDT)") or row.get("pnl") or 0.0)
                            if sym:
                                last_exit_pnl[sym] = pnl_val
            except Exception:
                pass

        kept_cd = {}
        for sym, iso_s in s_cd.items():
            try:
                dt = datetime.fromisoformat(str(iso_s).split("+")[0])
                rem_sec = (dt - now).total_seconds()
                if rem_sec <= 0:
                    changed = True
                    healed.append(f"{sym} 만료 쿨다운 청소")
                elif rem_sec > 1800 and last_exit_pnl.get(sym, -1.0) > 0:
                    changed = True
                    healed.append(f"{sym} 익절 후 오작동 쿨다운 자동 해제")
                else:
                    kept_cd[sym] = iso_s
            except Exception:
                changed = True
        if changed:
            stats["symbol_cooldown_until"] = kept_cd

    if changed:
        _atomic_write_json(stats_file, stats)

    eng_path = os.path.join(cwd, "core", "engine.py")
    if os.path.exists(eng_path):
        try:
            eng_src = open(eng_path, "r", encoding="utf-8").read()
            if "pnl < 0" not in eng_src and "is_loss" not in eng_src:
                return True, "core/engine.py 손절 한정 재진입 차단 가드(pnl < 0) 누락", False
        except Exception:
            pass

    if healed:
        return False, ", ".join(healed), True
    return False, "쿨다운/재진입 규칙 정상", False


# ── [모듈 8] 스캔 결과 유효성 · 지표 NaN/BTC 미확인 전수 감사 ───────────────
def check_scan_indicator_health(bot_id: int, cwd: str) -> Tuple[bool, str, bool]:
    """scan_results.json 전 종목 가격·화이트리스트 커버리지·지표 에러 여부를 점검한다."""
    cfg = _load_json(os.path.join(cwd, "config.json"))
    sr_path = os.path.join(cwd, "scan_results.json")
    sr = _load_json(sr_path)
    if not (isinstance(cfg, dict) and sr is not None):
        return False, "스캔 결과 없음", False
    if os.path.exists(sr_path) and (time.time() - os.path.getmtime(sr_path)) > 600:
        return False, "스캔 파일 10분 경과(Stall 감시 위임)", False

    res = sr.get("results", sr) if isinstance(sr, dict) else sr
    if not isinstance(res, list) or not res:
        return True, "scan_results.json 결과 비어 있음", False

    wl = list(cfg.get("SYMBOL_WHITELIST") or [])
    if str(cfg.get("EXCHANGE_ID", "okx")).lower() == "binance":
        wl = [s for s in wl if s not in ("OKB/USDT:USDT", "PEPE/USDT:USDT")]
    if wl and len(res) < len(wl) - 1:
        return True, f"화이트리스트 스캔 누락 ({len(res)}/{len(wl)})", True

    bad_px = [str(r.get("symbol")) for r in res if float(r.get("price") or 0) <= 0]
    if bad_px:
        return True, f"시세 0 이하 종목 감지 ({', '.join(bad_px[:3])})", False

    btc_unk = [str(r.get("symbol")) for r in res if "BTC=UNK" in str(r.get("reason", ""))]
    if btc_unk:
        return True, f"BTC 추세 필터 미확인(BTC=UNK)으로 진입 차단 상태 ({len(btc_unk)}종목)", True

    ind_err = [str(r.get("symbol")) for r in res if any(k in str(r.get("reason", "")) for k in ("지표 NaN/무효", "오류:"))]
    if ind_err:
        return True, f"지표 계산 오류 종목 감지 ({', '.join(ind_err[:3])})", False

    return False, f"스캔/지표 정상 ({len(res)}종목)", False


# ── [모듈 9] 7대 영역(Config ↔ TradingConfig ↔ Stats) 정합성 감사/치유 ─────
def check_full_stack_7zone_sync(bot_id: int, cwd: str) -> Tuple[bool, str]:
    """config.json, core/config.py, data/stats.json 간 핵심 설정·PeakMDD 정합성을 점검한다."""
    cfg = _load_json(os.path.join(cwd, "config.json"))
    core_cfg_path = os.path.join(cwd, "core", "config.py")
    if not (isinstance(cfg, dict) and os.path.exists(core_cfg_path)):
        return False, "설정 파일 없음"

    tf = str(cfg.get("TIMEFRAME", "")).strip().lower()
    meta = cfg.get("DASHBOARD_META") or {}
    if isinstance(meta, dict):
        m_tf = str(meta.get("timeframe", "")).strip().lower()
        m_strat = str(meta.get("strategy", "")).lower()
        if tf and m_tf and tf != m_tf:
            return True, f"7대영역 타임프레임 불일치 (config={tf} vs META={m_tf})"
        for tag in ("15m", "1h", "4h", "1d"):
            if f"({tag})" in m_strat and tf and tf != tag:
                return True, f"7대영역 전략태그 불일치 (config={tf} vs strategy={meta.get('strategy')})"

    try:
        core_src = open(core_cfg_path, "r", encoding="utf-8").read()
        missing = [k for k in ("DASHBOARD_META", "MAX_DRAWDOWN_PCT", "LEVERAGE", "TIMEFRAME") if k not in core_src]
        if missing:
            return True, f"core/config.py TradingConfig 필드 누락 ({', '.join(missing)})"
    except Exception:
        pass

    stats_file = os.path.join(cwd, "data", "stats.json")
    stats = _load_json(stats_file)
    if isinstance(stats, dict):
        seed = float(stats.get("seed_money", 0.0) or 0.0)
        peak = float(stats.get("peak_equity_usdt", 0.0) or 0.0)
        if seed > 0 and peak <= 0:
            stats["peak_equity_usdt"] = round(seed, 4)
            _atomic_write_json(stats_file, stats)
            return False, f"peak_equity_usdt 누락 자동 보정 (${seed:.2f})"

    return False, "7대영역 정합성 정상"


# ── [모듈 10] 보유 포지션 트레일링 컨텍스트 · prev_position_symbols 자동 복구
def check_position_context_integrity(bot_id: int, cwd: str) -> Tuple[bool, str]:
    """active_positions.json과 engine_states.json의 청산·트레일링 필수 상태를 자가 복원한다."""
    act_file = os.path.join(cwd, "data", "active_positions.json")
    pos_data = _load_json(act_file, {})
    if not isinstance(pos_data, dict) or not pos_data:
        return False, "포지션 없음(컨텍스트 대기 정상)"

    cfg = _load_json(os.path.join(cwd, "config.json"), {}) or {}
    def_act = float(cfg.get("TRAILING_ACTIVATE_PCT", 0.015) or 0.015)
    def_cb = float(cfg.get("TRAILING_CALLBACK_PCT", 0.008) or 0.008)

    repaired: List[str] = []
    act_changed = False
    for sym, info in pos_data.items():
        if not isinstance(info, dict):
            continue
        if not info.get("exit_profile"):
            info["exit_profile"] = "ATR" if cfg.get("USE_DYNAMIC_SLTP", False) else "SL/TP"
            act_changed = True
            repaired.append(f"{sym}:exit_profile")
        if float(info.get("atr_activation") or 0.0) <= 0:
            info["atr_activation"] = def_act
            act_changed = True
            repaired.append(f"{sym}:atr_activation")
        if float(info.get("atr_callback") or 0.0) <= 0:
            info["atr_callback"] = def_cb
            act_changed = True
            repaired.append(f"{sym}:atr_callback")
    if act_changed:
        _atomic_write_json(act_file, pos_data)

    eng_file = os.path.join(cwd, "data", "engine_states.json")
    es = _load_json(eng_file)
    if isinstance(es, dict):
        prev_syms = list(es.get("prev_position_symbols") or [])
        missing_prev = [s for s in pos_data if s not in prev_syms]
        if missing_prev:
            es["prev_position_symbols"] = list(dict.fromkeys(prev_syms + missing_prev))
            _atomic_write_json(eng_file, es)
            repaired.append(f"prev_position_symbols+{','.join(missing_prev)}")

    if repaired:
        return False, f"포지션 청산 컨텍스트 자동 복원 ({'; '.join(repaired)})"
    return False, f"포지션 컨텍스트 정상 ({len(pos_data)}건)"


# ── [모듈 11] 승패(W/L) ↔ 시퀀스(seq) 정합성 및 오분류 유령 청산행 자가 치유 ──
def check_ledger_seq_integrity(bot_id: int, cwd: str) -> Tuple[bool, str]:
    """
    1) trade_history.csv에서 진입 주문ID(주문ID)와 동일하면서 손익 0으로 오분류된
       유령 '청산' 행이 있으면 체결ID를 진입 행으로 보존한 뒤 자동 제거한다.
    2) extract_bot_metrics.py 기준 since_w/since_l과 seq의 O/x 개수가 100% 일치하는지 감사한다.
    """
    csv_path = os.path.join(cwd, "data", "trade_history.csv")
    if not os.path.exists(csv_path):
        return False, "거래장부 없음(정상)"

    stats_data = _load_json(os.path.join(cwd, "data", "stats.json"), {}) or {}
    perf_start = str(stats_data.get("perf_start_time") or "").strip()

    # 1) 진입 동일 order_id + pnl==0 오분류 유령 청산행 탐지 및 자가 치유
    healed_rows = 0
    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)

        if rows and fieldnames:
            entry_by_oid: Dict[str, int] = {}
            for idx, r in enumerate(rows):
                ts = str(r.get("시간") or "").strip()
                if perf_start and ts and ts < perf_start:
                    continue
                cat = str(r.get("유형") or "").strip()
                oid = str(r.get("주문ID") or "").strip()
                if cat in ("진입", "*진입") and oid:
                    entry_by_oid[oid] = idx

            drop_indices: Set[int] = set()
            for idx, r in enumerate(rows):
                ts = str(r.get("시간") or "").strip()
                if perf_start and ts and ts < perf_start:
                    continue
                cat = str(r.get("유형") or "").strip()
                oid = str(r.get("주문ID") or "").strip()
                try:
                    pnl = float(r.get("수익(USDT)") or 0.0)
                except Exception:
                    pnl = 0.0
                if cat in ("청산", "청산(로테이션)") and oid in entry_by_oid and abs(pnl) <= 1e-12:
                    e_idx = entry_by_oid[oid]
                    tid = str(r.get("체결ID") or "").strip()
                    if tid and not str(rows[e_idx].get("체결ID") or "").strip():
                        rows[e_idx]["체결ID"] = tid
                    drop_indices.add(idx)

            if drop_indices:
                healed_rows = len(drop_indices)
                cleaned_rows = [r for i, r in enumerate(rows) if i not in drop_indices]
                tmp = csv_path + ".tmp"
                with open(tmp, "w", encoding="utf-8-sig", newline="") as wf:
                    writer = csv.DictWriter(wf, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(cleaned_rows)
                os.replace(tmp, csv_path)
    except Exception:
        pass

    # 2) extract_bot_metrics.py 기준 since_w/since_l ↔ seq(O/x) 100% 일치 검증
    helper_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extract_bot_metrics.py")
    if os.path.exists(helper_path):
        try:
            res = subprocess.run(
                ["python3", helper_path, cwd, perf_start],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if res.returncode == 0 and res.stdout.strip():
                metrics = json.loads(res.stdout.strip().splitlines()[-1])
                if isinstance(metrics, dict) and "error" not in metrics:
                    sw = int(metrics.get("since_w") or 0)
                    sl = int(metrics.get("since_l") or 0)
                    seq = str(metrics.get("seq") or "")
                    total_wl = sw + sl
                    expected_len = min(30, total_wl)
                    if total_wl <= 30:
                        if seq.count("O") != sw or seq.count("x") != sl or len(seq) != total_wl:
                            return True, f"승패({sw}W/{sl}L)↔seq('{seq}') 불일치 감지"
                    elif len(seq) != expected_len:
                        return True, f"승패({sw}W/{sl}L)↔seq 길이({len(seq)}!={expected_len}) 불일치 감지"
        except Exception:
            pass

    if healed_rows > 0:
        return False, f"오분류 유령 청산행 {healed_rows}건 자동 제거(체결ID 보존)"
    return False, "승패↔seq 정합성 정상"


# ── 통합 오케스트레이터 (모듈 2/3/4/6/7/8/9/10/11 일괄 점검) ───────────────────
# ── 모듈 12: 자가치유 무한 반복(핑퐁 루프) & 동일 오류 반복 재기동 감시 ─────
def check_self_heal_loop_and_repeat_restarts(bot_id: int, cwd: str) -> Tuple[bool, str]:
    """
    모듈 12:
      1) sentinel_action_history.json 내 동일 치유 액션이 30분 내 3회 이상 반복 시 충돌/루프로 적발
      2) /tmp/watchdog_restart_state.json 내 동일 오류 시그니처 재기동이 60분 내 2회 이상이면 적발
    """
    bid = str(bot_id)
    now = time.time()
    base_8888 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hist_path = os.path.join(base_8888, "data", "sentinel_action_history.json")
    hist = _load_json(hist_path, {}) or {}
    bot_hist = hist.get(bid) or {}
    if isinstance(bot_hist, dict):
        for bucket, ts_list in bot_hist.items():
            if isinstance(ts_list, list):
                recent = [t for t in ts_list if (now - float(t or 0.0)) <= 1800]
                if len(recent) >= 3:
                    return True, f"자가치유 핑퐁 루프 감지: {bucket} ({len(recent)}회/30m)"

    rstate = _load_json("/tmp/watchdog_restart_state.json", {}) or {}
    brec = rstate.get(bid) or {}
    if isinstance(brec, dict):
        counts: Dict[str, int] = {}
        for att in (brec.get("recent_attempts") or []):
            if not isinstance(att, dict):
                continue
            if (now - float(att.get("ts") or 0.0)) <= 3600:
                sig = str(att.get("sig") or "")
                if sig:
                    counts[sig] = counts.get(sig, 0) + 1
        for sig, cnt in counts.items():
            if cnt >= 2:
                return True, f"동일 오류 반복 재기동 감지: {sig} ({cnt}회/60m)"

    return False, "자가치유 루프·반복 재기동 없음"


def run_all_autonomous_audits(bot_id: int, cwd: str) -> Dict[str, Any]:
    """모듈 1(별도 상시)·모듈 5/10b(bot_sentinel) 외 통합 모듈을 실행해 보고/조치 데이터를 반환한다."""
    issues: List[Tuple[str, str]] = []
    healed: List[str] = []
    needs_restart = False

    trace_err, trace_msg, trace_rst = check_unexecuted_signal_trace(bot_id, cwd)
    if trace_err:
        issues.append(("ai_unexecuted_signal_trace", trace_msg))
        needs_restart = needs_restart or trace_rst

    size_err, size_msg = check_order_sizing_preflight(bot_id, cwd)
    if size_err:
        issues.append(("ai_sizing_preflight", size_msg))

    gate_err, gate_msg = check_signal_gate_contract(bot_id, cwd)
    if gate_err:
        issues.append(("ai_signal_gate_contract", gate_msg))

    fd_err, fd_msg, fd_rst = check_log_fd_and_pid_lock_integrity(bot_id, cwd)
    if fd_err:
        issues.append(("ai_log_fd_pid_lock", fd_msg))
        needs_restart = needs_restart or fd_rst
    elif "동기화" in fd_msg:
        healed.append(fd_msg)

    cd_err, cd_msg, cd_rst = check_cooldown_and_reentry_integrity(bot_id, cwd)
    if cd_err:
        issues.append(("ai_cooldown_reentry", cd_msg))
    elif "해제" in cd_msg or "청소" in cd_msg:
        healed.append(cd_msg)
        needs_restart = needs_restart or cd_rst

    scan_err, scan_msg, scan_rst = check_scan_indicator_health(bot_id, cwd)
    if scan_err:
        issues.append(("ai_scan_indicator_health", scan_msg))
        needs_restart = needs_restart or scan_rst

    sync_err, sync_msg = check_full_stack_7zone_sync(bot_id, cwd)
    if sync_err:
        issues.append(("ai_7zone_sync", sync_msg))
    elif "보정" in sync_msg:
        healed.append(sync_msg)

    ctx_err, ctx_msg = check_position_context_integrity(bot_id, cwd)
    if ctx_err:
        issues.append(("ai_position_context", ctx_msg))
    elif "복원" in ctx_msg:
        healed.append(ctx_msg)

    seq_err, seq_msg = check_ledger_seq_integrity(bot_id, cwd)
    if seq_err:
        issues.append(("ai_ledger_seq_integrity", seq_msg))
    elif "제거" in seq_msg:
        healed.append(seq_msg)

    loop_err, loop_msg = check_self_heal_loop_and_repeat_restarts(bot_id, cwd)
    if loop_err:
        issues.append(("ai_self_heal_loop", loop_msg))

    return {
        "issues": issues,
        "healed": healed,
        "needs_restart": needs_restart,
        "gate_summary": gate_msg,
        "scan_summary": scan_msg,
    }
