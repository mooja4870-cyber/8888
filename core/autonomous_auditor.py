#!/usr/bin/env python3
"""
autonomous_auditor.py — 8888 AI 자율 감시·선제 발굴·자가 치유 엔진

매매 전 파이프라인(코드-메모리 동기화 → 시그널-게이트 계약 → 주문 수량 프리플라이트 →
미체결 시그널 역추적 및 스테일 락 해제)을 상시 자동 감사하여 조용한 매매 저해 요인을
보스 질문 이전에 선제 탐지·조치한다.
"""
import ast
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

BASE_8888 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_SIZES_FILE = os.path.join(BASE_8888, "data", "contract_sizes.json")


def _atomic_write_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _get_running_bot_pid(bot_id: int, cwd: str) -> Optional[int]:
    """실행 중인 bot.py의 실제 PID를 lock/pid 파일에서 조회한다."""
    for path in (f"/tmp/quantum_{bot_id}_trader.lock", os.path.join(cwd, "bot.pid")):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if raw.isdigit():
                pid = int(raw)
                res = subprocess.run(["kill", "-0", str(pid)], capture_output=True)
                if res.returncode == 0:
                    return pid
        except Exception:
            continue
    return None


def _get_process_start_epoch(pid: int) -> Optional[float]:
    """macOS `ps -p <pid> -o lstart=` 출력에서 프로세스 기동 epoch를 파싱한다."""
    try:
        res = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=3,
        )
        raw = " ".join((res.stdout or "").strip().split())
        if not raw:
            return None
        return datetime.strptime(raw, "%a %b %d %H:%M:%S %Y").timestamp()
    except Exception:
        return None


def check_stale_code_sync(bot_id: int, cwd: str) -> Tuple[bool, str]:
    """[모듈 1] 디스크 코드(bot.py, core/*.py) 수정 후 미재기동 상태 탐지."""
    pid = _get_running_bot_pid(bot_id, cwd)
    if pid is None:
        return False, "실행 PID 없음 (생존 감시 위임)"

    proc_start_ts = _get_process_start_epoch(pid)
    if proc_start_ts is None:
        return False, "기동 시각 조회 불가"

    watch_files: List[str] = []
    bot_py = os.path.join(cwd, "bot.py")
    if os.path.exists(bot_py):
        watch_files.append(bot_py)
    core_dir = os.path.join(cwd, "core")
    if os.path.isdir(core_dir):
        for fn in os.listdir(core_dir):
            if fn.endswith(".py"):
                watch_files.append(os.path.join(core_dir, fn))

    now_ts = time.time()
    newer_files: List[str] = []
    for fp in watch_files:
        try:
            mtime = os.path.getmtime(fp)
            if mtime > proc_start_ts + 30.0 and (now_ts - mtime) > 15.0:
                newer_files.append(os.path.relpath(fp, cwd))
        except OSError:
            continue

    if newer_files:
        sample = ", ".join(sorted(newer_files)[:3])
        suffix = f" 외 {len(newer_files) - 3}건" if len(newer_files) > 3 else ""
        return True, f"디스크 코드 수정 후 미재기동 감지 ({sample}{suffix})"
    return False, "코드-메모리 동기화 정상"


def _eval_str_consts(tree: ast.AST) -> Dict[str, str]:
    consts: Dict[str, str] = {}
    if isinstance(tree, ast.Module):
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                t = node.targets[0]
                if isinstance(t, ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    consts[t.id] = node.value.value
    return consts


def _extract_signal_min_strength(expr: Optional[ast.AST]) -> Optional[int]:
    if expr is None:
        return None
    if isinstance(expr, ast.Constant) and isinstance(expr.value, (int, float)):
        return int(expr.value)
    if isinstance(expr, ast.IfExp):
        # 예: `85 if direction != "none" else 0` → 활성 경로 강도(body) 우선 추출
        if isinstance(expr.body, ast.Constant) and isinstance(expr.body.value, (int, float)):
            return int(expr.body.value)
        if isinstance(expr.orelse, ast.Constant) and isinstance(expr.orelse.value, (int, float)):
            return int(expr.orelse.value)
    return None


def _is_none_direction_signal(call_node: ast.Call) -> bool:
    for kw in call_node.keywords:
        if kw.arg == "direction" and isinstance(kw.value, ast.Constant) and kw.value.value == "none":
            return True
    if len(call_node.args) >= 2 and isinstance(call_node.args[1], ast.Constant) and call_node.args[1].value == "none":
        return True
    return False


def _parse_strategy_outputs(strat_path: str) -> Tuple[Set[str], int]:
    """core/strategy.py에서 활성 Signal의 strategy_type 후보와 최소 강도를 추출한다."""
    with open(strat_path, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=strat_path)
    consts = _eval_str_consts(tree)

    default_strat_type: Optional[str] = None
    emitted_types: Set[str] = set()
    active_strengths: List[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Signal":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == "strategy_type":
                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        default_strat_type = stmt.value.value
                    elif isinstance(stmt.value, ast.Name) and stmt.value.id in consts:
                        default_strat_type = consts[stmt.value.id]
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "strategy_type":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        emitted_types.add(node.value.value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Signal":
            if _is_none_direction_signal(node):
                continue
            kw_map = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            st_val = kw_map.get("strategy_type")
            if isinstance(st_val, ast.Constant) and isinstance(st_val.value, str):
                emitted_types.add(st_val.value)
            elif isinstance(st_val, ast.Name) and st_val.id in consts:
                emitted_types.add(consts[st_val.id])

            s_expr = kw_map.get("strength")
            if s_expr is None and len(node.args) >= 3:
                s_expr = node.args[2]
            s_val = _extract_signal_min_strength(s_expr)
            if s_val is not None and s_val > 0:
                active_strengths.append(s_val)

    if not emitted_types and default_strat_type:
        emitted_types.add(default_strat_type)

    min_strength = min(active_strengths) if active_strengths else 100
    return emitted_types, min_strength


def _extract_gate_strings(test_node: ast.AST) -> List[str]:
    found: List[str] = []
    for n in ast.walk(test_node):
        if isinstance(n, ast.Compare):
            for c in n.comparators:
                for sub in ast.walk(c):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value:
                        found.append(sub.value)
    return list(dict.fromkeys(found))


def _collect_if_chain(if_node: ast.If, gate_map: Dict[str, int], default_box: List[int]) -> None:
    keys = _extract_gate_strings(if_node.test)
    for stmt in if_node.body:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name) and t.id == "required_strength" and isinstance(stmt.value, ast.Constant):
                    if isinstance(stmt.value.value, (int, float)):
                        for k in keys:
                            gate_map[k] = int(stmt.value.value)
    if if_node.orelse:
        if len(if_node.orelse) == 1 and isinstance(if_node.orelse[0], ast.If):
            _collect_if_chain(if_node.orelse[0], gate_map, default_box)
        else:
            for stmt in if_node.orelse:
                if isinstance(stmt, ast.Assign):
                    for t in stmt.targets:
                        if isinstance(t, ast.Name) and t.id == "required_strength" and isinstance(stmt.value, ast.Constant):
                            if isinstance(stmt.value.value, (int, float)):
                                default_box[0] = int(stmt.value.value)


def _parse_trader_strength_gates(trader_path: str) -> Tuple[Dict[str, int], int]:
    """core/trader.py _risk_check()에서 strategy_type별 required_strength 맵을 추출한다."""
    with open(trader_path, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=trader_path)
    gate_map: Dict[str, int] = {}
    default_box = [90]

    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "_risk_check":
            for stmt in node.body:
                if isinstance(stmt, ast.If) and "required_strength" in ast.dump(stmt):
                    _collect_if_chain(stmt, gate_map, default_box)
    return gate_map, default_box[0]


def check_signal_gate_contract(bot_id: int, cwd: str) -> Tuple[bool, str]:
    """[모듈 4] strategy.py 생성 시그널 강도와 trader.py _risk_check() 게이트 정합성 검사."""
    strat_path = os.path.join(cwd, "core", "strategy.py")
    trader_path = os.path.join(cwd, "core", "trader.py")
    if not (os.path.exists(strat_path) and os.path.exists(trader_path)):
        return False, "전략/트레이더 파일 없음"

    try:
        emitted_types, min_strength = _parse_strategy_outputs(strat_path)
        gate_map, default_req = _parse_trader_strength_gates(trader_path)
    except Exception as e:
        return False, f"시그널-게이트 정적 분석 스킵 ({e})"

    if not emitted_types:
        return False, "활성 시그널 유형 추출 불가(스킵)"

    mismatches: List[str] = []
    for st in sorted(emitted_types):
        req = gate_map.get(st, default_req)
        if min_strength < req:
            mismatches.append(f"{st}: 생성강도 {min_strength}% < 필요강도 {req}%")

    if mismatches:
        return True, f"시그널-게이트 불일치 감지 ({'; '.join(mismatches)})"
    return False, f"시그널-게이트 정합 정상 ({','.join(sorted(emitted_types))}≥{min_strength}%)"


def check_order_sizing_preflight(bot_id: int, cwd: str) -> Tuple[bool, str]:
    """[모듈 3] exchange.py 최소주문 보정 가드 및 화이트리스트 진입 수량 가능성 프리플라이트 점검."""
    ex_path = os.path.join(cwd, "core", "exchange.py")
    cfg_path = os.path.join(cwd, "config.json")
    if not os.path.exists(ex_path) or not os.path.exists(cfg_path):
        return False, "설정/거래소 모듈 없음"

    try:
        with open(ex_path, "r", encoding="utf-8") as f:
            ex_src = f.read()
        if "[MIN AMOUNT ADJUST]" not in ex_src:
            return True, "exchange.py 최소 주문 수량 자동 보정([MIN AMOUNT ADJUST]) 가드 누락"

        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        margin_usdt = float(cfg.get("MARGIN_USDT", 0.0) or 0.0)
        eq_scale = float(cfg.get("EQUITY_SCALE_FACTOR", 1.0) or 1.0)
        lev = float(cfg.get("LEVERAGE", 3.0) or 3.0)
        use_compound = bool(cfg.get("USE_AUTO_COMPOUND", False))
        risk_pct = float(cfg.get("RISK_PER_TRADE_PCT", 0.0) or 0.0)

        if not use_compound and risk_pct <= 0 and (margin_usdt * eq_scale) < 1.0:
            return True, f"고정 증거금 설정 과소 ({margin_usdt * eq_scale:.2f} USDT < 1.0 USDT)"
        if lev <= 0:
            return True, f"레버리지 설정 오류 ({lev})"
    except Exception as e:
        return False, f"사이징 프리플라이트 스킵 ({e})"

    return False, "주문 사이징 프리플라이트 정상"


def check_unexecuted_signal_trace(bot_id: int, cwd: str) -> Tuple[bool, str, bool]:
    """[모듈 2] 무포지션 봇의 스테일 락 자동 청소 및 최근 시그널 미체결 차단 원인 추적.

    반환: (이상 감지 여부, 상세 사유, 재기동 필요 여부)
    """
    act_file = os.path.join(cwd, "data", "active_positions.json")
    if os.path.exists(act_file):
        try:
            with open(act_file, "r", encoding="utf-8") as f:
                pos_data = json.load(f)
            if pos_data and len(pos_data) > 0:
                return False, "보유 포지션 있음", False
        except Exception:
            pass

    now_local = datetime.now()

    # 1) engine_states.json 내 10분(600초) 초과 만료 recently_entered 락 자동 해제
    eng_state_file = os.path.join(cwd, "data", "engine_states.json")
    if os.path.exists(eng_state_file):
        try:
            with open(eng_state_file, "r", encoding="utf-8") as f:
                estate = json.load(f)
            rec = estate.get("recently_entered") or {}
            if isinstance(rec, dict) and rec:
                kept = {}
                stale_syms = []
                for sym, ts_str in rec.items():
                    try:
                        dt = datetime.fromisoformat(str(ts_str).split("+")[0])
                        if (now_local - dt).total_seconds() <= 600:
                            kept[sym] = ts_str
                        else:
                            stale_syms.append(sym)
                    except Exception:
                        stale_syms.append(sym)
                if stale_syms:
                    estate["recently_entered"] = kept
                    _atomic_write_json(eng_state_file, estate)
                    return True, f"만료된 recently_entered 락 잔존 자동 해제 ({', '.join(stale_syms)})", True
        except Exception:
            pass

    # 2) 최근 30분 내 [SIG]/[SIGNAL] 발생 후 미체결 차단 원인 역추적
    now_kst = datetime.utcnow() + timedelta(hours=9)
    log_path = os.path.join(cwd, "bot_engine.log")
    if not os.path.exists(log_path):
        log_path = os.path.join(cwd, "bot_stdout.log")
    if not os.path.exists(log_path):
        return False, "신호 트레이스 로그 없음", False

    try:
        with open(log_path, "rb") as lf:
            lf.seek(0, os.SEEK_END)
            size = lf.tell()
            lf.seek(max(0, size - 32768))
            tail = lf.read().decode("utf-8", errors="ignore")
    except Exception:
        return False, "신호 트레이스 읽기 실패", False

    recent_sig_lines: List[str] = []
    recent_block_lines: List[str] = []
    sig_tags = ("[sig]", "[signal]", "[fusion signal]", "[donchian signal]")
    block_tags = (
        "trader disabled",
        "신호 강도 부족",
        "최소 주문 단위",
        "minimum amount precision",
        "[entry block]",
        "[risk block]",
    )

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
        if any(t in low for t in sig_tags):
            recent_sig_lines.append(ls)
        if any(t in low for t in block_tags):
            recent_block_lines.append(ls)

    if recent_sig_lines and recent_block_lines:
        last_block = recent_block_lines[-1]
        low_b = last_block.lower()
        if "trader disabled" in low_b:
            return True, f"최근 시그널 발생 후 trader disabled 차단 감지 ({last_block[:90]})", True
        if "신호 강도 부족" in last_block or "최소 주문 단위" in last_block or "minimum amount precision" in low_b:
            return True, f"최근 시그널 게이트/수량 차단 감지 ({last_block[:110]})", False

    return False, "미체결 차단 이상 없음", False
