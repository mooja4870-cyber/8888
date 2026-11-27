"""
core/auto_remediator.py — Aegis V8.5 Profit-Adaptive Closed-Loop 자율 적기 조치 엔진 (보스 위임 2026-11-27)

워치독 감시 활동에서 포착된 문제점에 대해 보스 사전 승인 대기 없이
안전한 클램프·쿨다운·사전 백업(.auto_bak)·공유 락 재기동(bot_restart_locked)·
디스코드 사후 보고·사후 수익성 검증 및 자동 롤백을 결합하여 수익성 향상 방향으로 자율 조치를 수행한다.

Playbooks:
  - R1: 진입 사이징/최소명목가 오류(NOTIONAL_MIN_ERROR 등) 자동 보정 (6h 쿨다운)
  - R2: Peak-MDD 주의/킬선 도달 시 자동 비중 축소·방향고정·킬선 진입정지 (12h 쿨다운)
  - R3: 수수료 적자/조기 알파 감쇠 시 단계적 파라미터·타임프레임 자율 튜닝 (24h 쿨다운)
  - R4: 생존 설정 누락(config_gap) 자동 복구 (12h 쿨다운)
  - R8: R3/R10 자율 변경 사후 수익성 검증 및 성과 악화 시 자동 롤백 + 7일 재적용 차단
  - R9: R2/R3 방어 축소 이후 수익 회복 시 원래 기준치까지 단계적 복구 스케일업 (24h 쿨다운)
  - R10: 최근 14일 만성 손실 종목 화이트리스트 자율 제외 (최소 16종목·보유포지션 보호, 24h 쿨다운)
  - Deferred Apply: 보유 포지션 청산 직후 유예된 config 재기동 자동 완결
  - Helper: 외부 모듈(bot_sentinel R6/R7, autonomous_auditor R5) 이력 기록 및 보고
"""
import copy
import csv
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from watchdog_common import (
    BASE_8888,
    BASE_PROJECT,
    bot_restart_locked,
    send_autonomous_action_report,
)

HISTORY_FILE = os.path.join(BASE_8888, "data", "auto_remediation_history.json")
HISTORY_LOCK = "/tmp/watchdog_auto_remediation.lock"

MIN_WHITELIST_SIZE = 16
R8_MIN_POST_TRADES = 10
R8_MAX_WAIT_SEC = 72 * 3600
R8_MIN_TRADES_AFTER_WAIT = 4
R8_EXPIRE_SEC = 14 * 86400
R8_BLOCK_SEC = 7 * 86400


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _parse_local_dt(val: str) -> Optional[dt.datetime]:
    if not val or not isinstance(val, str):
        return None
    s = val.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def _read_bot_trade_rows(cwd: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Read perf_start_time-filtered fee rows and order-grouped closed trades from trade_history.csv."""
    stats = _load_json(os.path.join(cwd, "data", "stats.json"), {}) or {}
    perf_start_dt = _parse_local_dt(str(stats.get("perf_start_time") or ""))
    csv_path = os.path.join(cwd, "data", "trade_history.csv")
    all_fee_rows: List[Dict[str, Any]] = []
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if not os.path.exists(csv_path):
        return all_fee_rows, []

    anon_seq = 0
    try:
        with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_str = (row.get("시간") or row.get("time") or "").strip()
                ts_dt = _parse_local_dt(ts_str)
                if ts_dt is None:
                    continue
                if perf_start_dt and ts_dt < perf_start_dt:
                    continue
                ts_epoch = ts_dt.timestamp()
                sym = (row.get("심볼") or row.get("symbol") or "").strip()
                fee = abs(_safe_float(row.get("수수료(USDT)") or row.get("fee"), 0.0))
                all_fee_rows.append({"ts": ts_epoch, "symbol": sym, "fee": fee})

                row_type = (row.get("유형") or row.get("type") or "").strip()
                is_close = ("청산" in row_type) or (row_type.lower() == "close")
                if not is_close:
                    continue

                pnl = _safe_float(row.get("수익(USDT)") or row.get("pnl"), 0.0)
                ord_id = (row.get("주문ID") or row.get("order_id") or "").strip()
                if ord_id and ord_id.lower() not in ("none", "null", "nan", "0"):
                    key = (ord_id, sym)
                else:
                    anon_seq += 1
                    key = (f"__row_{anon_seq}", sym)

                if key not in grouped:
                    grouped[key] = {
                        "ts": ts_epoch,
                        "ts_str": ts_str,
                        "symbol": sym,
                        "pnl": 0.0,
                        "close_fee": 0.0,
                    }
                grouped[key]["pnl"] += pnl
                grouped[key]["close_fee"] += fee
    except Exception:
        return all_fee_rows, []

    closes = sorted(grouped.values(), key=lambda x: x["ts"])
    return all_fee_rows, closes


def _compute_window_metrics(
    cwd: str, since_ts: Optional[float] = None, last_n: Optional[int] = None
) -> Dict[str, Any]:
    """Compute order-grouped closed trade metrics for a time window or last N trades."""
    all_fee_rows, closes = _read_bot_trade_rows(cwd)
    if since_ts is not None:
        closes = [c for c in closes if c["ts"] >= since_ts]
    if last_n is not None and last_n > 0:
        closes = closes[-last_n:]

    n = len(closes)
    if n == 0:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "gross_pnl": 0.0,
            "fees": 0.0,
            "net_pnl": 0.0,
            "pf": 0.0,
            "expectancy": 0.0,
        }

    close_fee_sum = sum(c["close_fee"] for c in closes)
    if since_ts is not None:
        win_fees = sum(r["fee"] for r in all_fee_rows if r["ts"] >= since_ts)
    else:
        entry_cutoff = closes[0]["ts"] - 3600.0
        win_fees = max(
            close_fee_sum,
            sum(r["fee"] for r in all_fee_rows if r["ts"] >= entry_cutoff),
        )

    wins = sum(1 for c in closes if c["pnl"] > 0)
    losses = sum(1 for c in closes if c["pnl"] < 0)
    gross_win = sum(c["pnl"] for c in closes if c["pnl"] > 0)
    gross_loss = abs(sum(c["pnl"] for c in closes if c["pnl"] < 0))
    gross_pnl = round(sum(c["pnl"] for c in closes), 4)
    fees = round(win_fees, 4)
    net_pnl = round(gross_pnl - fees, 4)
    if gross_loss > 0:
        pf = round(gross_win / gross_loss, 3)
    elif gross_win > 0:
        pf = 9.99
    else:
        pf = 0.0
    win_rate = round((wins / n) * 100.0, 1)
    expectancy = round(net_pnl / n, 4)
    return {
        "trades": n,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "pf": pf,
        "expectancy": expectancy,
    }


def _load_json(path: str, default: Any = None) -> Any:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default if default is not None else {}


def _atomic_write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _ensure_history_shape(doc: Any) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        doc = {}
    doc.setdefault("last_runs", {})
    doc.setdefault("events", [])
    doc.setdefault("pre_defense_baseline", {})
    doc.setdefault("pending_restarts", {})
    doc.setdefault("blocked_actions", {})
    return doc


def _is_action_blocked(bot_id: str, sig: str) -> bool:
    now = time.time()
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
            blocked = doc.get("blocked_actions") or {}
            exp = _safe_float(blocked.get(f"{bot_id}:{sig}"), 0.0)
            return exp > now
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _record_pre_defense_baseline(
    bot_id: str, orig_values: Dict[str, Any], keys: List[str]
) -> None:
    if not keys or not orig_values:
        return
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
            pre_map = doc["pre_defense_baseline"].setdefault(str(bot_id), {})
            changed = False
            for k in keys:
                if k in orig_values and k not in pre_map:
                    pre_map[k] = copy.deepcopy(orig_values[k])
                    changed = True
            if changed:
                _atomic_write_json(HISTORY_FILE, doc)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _check_and_mark_cooldown(
    bot_id: str, playbook: str, cooldown_sec: int, dry_run: bool = False
) -> Tuple[bool, float]:
    """Return (allowed, remaining_sec)."""
    now = time.time()
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
            last_runs = doc["last_runs"]
            key = f"{bot_id}:{playbook}"
            last_ts = float(last_runs.get(key) or 0.0)
            elapsed = now - last_ts
            if elapsed < cooldown_sec:
                return False, round(cooldown_sec - elapsed, 1)
            if not dry_run:
                last_runs[key] = now
                _atomic_write_json(HISTORY_FILE, doc)
            return True, 0.0
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _append_history_event(
    bot_id: str,
    playbook: str,
    title: str,
    actions: List[str],
    reason: str,
    severity: str = "INFO",
    notify_discord: bool = True,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    now = time.time()
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
            last_runs = doc["last_runs"]
            events = doc["events"]
            last_runs[f"{bot_id}:{playbook}"] = now
            ev: Dict[str, Any] = {
                "ts": now,
                "ts_str": now_str,
                "bot_id": str(bot_id),
                "playbook": playbook,
                "severity": severity,
                "title": title,
                "actions": list(actions),
                "reason": str(reason)[:240],
            }
            if extra and isinstance(extra, dict):
                ev.update(copy.deepcopy(extra))
            events.append(ev)
            doc["events"] = events[-200:]
            doc["updated"] = now_str
            _atomic_write_json(HISTORY_FILE, doc)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    if notify_discord and actions:
        send_autonomous_action_report(
            str(bot_id), title, actions, reason, severity=severity
        )


def record_external_remediation(
    bot_id: str,
    playbook: str,
    title: str,
    actions: List[str],
    reason: str,
    severity: str = "INFO",
    notify_discord: bool = True,
) -> None:
    """Record remediation performed by bot_sentinel or autonomous_auditor."""
    _append_history_event(
        bot_id, playbook, title, actions, reason, severity=severity, notify_discord=notify_discord
    )


def _load_bot_config_with_backup(cwd: str) -> Tuple[str, Dict[str, Any]]:
    cfg_path = os.path.join(cwd, "config.json")
    cfg = _load_json(cfg_path, {})
    if not isinstance(cfg, dict):
        cfg = {}
    return cfg_path, cfg


def _save_bot_config_with_backup(cfg_path: str, cfg: Dict[str, Any]) -> None:
    if os.path.exists(cfg_path):
        shutil.copy2(cfg_path, f"{cfg_path}.auto_bak")
    tmp = f"{cfg_path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)
    os.replace(tmp, cfg_path)


def _sync_ver_md(bot_dir: str, headline: str, bullets: List[str]) -> None:
    """Append concise autonomous remediation log into bot/ver.md (non-fatal)."""
    ver_path = os.path.join(bot_dir, "ver.md")
    if not os.path.exists(ver_path):
        return
    try:
        with open(ver_path, "r", encoding="utf-8") as f:
            old = f.read()
        today = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"\n<!-- Aegis V8 Autonomous Action {today} -->\n"
            f"- **[자율 조치 {today}]** {headline}\n"
            + "".join(f"  - {b}\n" for b in bullets)
        )
        marker = "## v"
        idx = old.find(marker)
        if idx != -1:
            new_txt = entry.lstrip("\n") + "\n" + old if idx == 0 else old[:idx] + entry + "\n" + old[idx:]
        else:
            new_txt = entry + "\n" + old
        with open(ver_path, "w", encoding="utf-8") as f:
            f.write(new_txt)
    except Exception:
        pass


def _should_hold_restart_for_positions(cwd: str) -> bool:
    act_path = os.path.join(cwd, "data", "active_positions.json")
    act = _load_json(act_path, {})
    return isinstance(act, dict) and len(act) > 0


def _update_pending_restart(
    bot_id: str, restarted: bool, playbook: str, title: str, cwd: str
) -> None:
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    now = time.time()
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
            pend = doc["pending_restarts"]
            bid = str(bot_id)
            if restarted:
                changed = False
                if bid in pend:
                    pend.pop(bid, None)
                    changed = True
                for ev in doc["events"]:
                    if (
                        str(ev.get("bot_id")) == bid
                        and ev.get("eval_status") == "pending"
                        and not ev.get("activated_ts")
                    ):
                        ev["activated_ts"] = now
                        changed = True
                if changed:
                    _atomic_write_json(HISTORY_FILE, doc)
            else:
                pend[bid] = {
                    "ts": now,
                    "ts_str": now_str,
                    "playbook": playbook,
                    "reason": str(title)[:200],
                    "cwd": cwd,
                }
                _atomic_write_json(HISTORY_FILE, doc)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _apply_and_restart(
    bot_id: str,
    cwd: str,
    playbook: str,
    title: str,
    actions: List[str],
    reason: str,
    cfg_path: str,
    cfg: Dict[str, Any],
    severity: str = "INFO",
    force_restart_with_pos: bool = False,
    prev_values: Optional[Dict[str, Any]] = None,
    baseline_metrics: Optional[Dict[str, Any]] = None,
    eval_status: str = "skipped_na",
    block_sigs: Optional[List[str]] = None,
    record_defense_baseline_keys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if record_defense_baseline_keys and prev_values:
        _record_pre_defense_baseline(bot_id, prev_values, record_defense_baseline_keys)

    _save_bot_config_with_backup(cfg_path, cfg)
    _sync_ver_md(cwd, title, actions)

    has_pos = _should_hold_restart_for_positions(cwd)
    restarted = False
    restart_detail = "deferred_active_position"
    if (not has_pos) or force_restart_with_pos:
        ok, detail = bot_restart_locked(
            str(bot_id), cwd, source=f"aegis_v8_{playbook}", reason=title, cooldown_sec=60
        )
        restarted = bool(ok)
        restart_detail = detail
        if restarted:
            actions.append(f"엔진 안전 재기동 완료 ({detail})")
        else:
            actions.append(f"설정 디스크 반영 완료 (재기동 보류: {detail})")
    else:
        actions.append("설정 디스크 반영 완료 (보유 포지션 보호로 재기동 유예)")

    _update_pending_restart(str(bot_id), restarted, playbook, title, cwd)

    extra: Dict[str, Any] = {"eval_status": eval_status}
    if prev_values:
        extra["prev_values"] = copy.deepcopy(prev_values)
    if baseline_metrics:
        extra["baseline_metrics"] = copy.deepcopy(baseline_metrics)
    if block_sigs:
        extra["block_sigs"] = list(block_sigs)
    if restarted:
        extra["activated_ts"] = time.time()

    _append_history_event(
        str(bot_id), playbook, title, actions, reason, severity=severity, notify_discord=True, extra=extra
    )
    return {"applied": True, "restarted": restarted, "restart_detail": restart_detail, "actions": actions}


def _disable_auto_switch(cfg: Dict[str, Any], actions: List[str]) -> bool:
    changed = False
    if cfg.get("USE_AUTO_MODE_SWITCH"):
        cfg["USE_AUTO_MODE_SWITCH"] = False
        actions.append("USE_AUTO_MODE_SWITCH: True→False (엇박자 반전 차단)")
        changed = True
    if cfg.get("USE_BLUEFROG"):
        cfg["USE_BLUEFROG"] = False
        actions.append("USE_BLUEFROG: True→False (순방향 고정)")
        changed = True
    meta = cfg.get("DASHBOARD_META")
    if isinstance(meta, dict) and meta.get("auto_switch"):
        meta["auto_switch"] = False
        changed = True
    return changed


def remediate_entry_sizing_error(bot_id: str, cwd: str, err_type: str) -> Dict[str, Any]:
    """[Playbook R1] NOTIONAL_MIN_ERROR / MARGIN_SETTING_ERROR 자동 복구."""
    if err_type not in ("NOTIONAL_MIN_ERROR", "MARGIN_SETTING_ERROR"):
        return {"applied": False, "skipped": "unsupported_err_type"}

    allowed, rem = _check_and_mark_cooldown(bot_id, "R1_sizing", cooldown_sec=21600, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []
    lev = max(float(cfg.get("LEVERAGE", 3.0) or 3.0), 1.0)
    ex_id = str(cfg.get("EXCHANGE_ID", "")).lower()

    if float(cfg.get("EQUITY_SCALE_FACTOR", 1.0) or 1.0) < 1.0:
        old_s = cfg.get("EQUITY_SCALE_FACTOR")
        prev_values["EQUITY_SCALE_FACTOR"] = orig_cfg.get("EQUITY_SCALE_FACTOR")
        cfg["EQUITY_SCALE_FACTOR"] = 1.0
        actions.append(f"EQUITY_SCALE_FACTOR: {old_s}→1.0")
    if ex_id == "binance" and cfg.get("USE_EQUITY_OVERLAY", False) is not False:
        prev_values["USE_EQUITY_OVERLAY"] = orig_cfg.get("USE_EQUITY_OVERLAY")
        cfg["USE_EQUITY_OVERLAY"] = False
        actions.append("USE_EQUITY_OVERLAY: False")

    min_safe_margin = min(3.5, round(5.5 / lev, 2))
    cur_margin = float(cfg.get("MARGIN_USDT", 1.5) or 1.5)
    if cur_margin < min_safe_margin:
        prev_values["MARGIN_USDT"] = orig_cfg.get("MARGIN_USDT")
        cfg["MARGIN_USDT"] = min_safe_margin
        actions.append(f"MARGIN_USDT: ${cur_margin:.2f}→${min_safe_margin:.2f} (명목가≥$5.5 보장)")

    if not actions:
        return {"applied": False, "skipped": "already_safe"}

    return _apply_and_restart(
        bot_id,
        cwd,
        "R1_sizing",
        f"진입 주문 규격 오류({err_type}) 자율 보정",
        actions,
        reason=f"{err_type} 감지로 최소 주문 명목가 충족 보정",
        cfg_path=cfg_path,
        cfg=cfg,
        severity="WARN",
        force_restart_with_pos=False,
        prev_values=prev_values,
        eval_status="skipped_na",
    )


def remediate_peak_mdd(
    bot_id: str,
    cwd: str,
    peak_dd_pct: float,
    is_kill: bool,
    mdd_warn: float,
    mdd_kill: float,
) -> Dict[str, Any]:
    """[Playbook R2] Peak-MDD 주의/킬선 자동 방어 (비중 축소·방향 고정·킬선 진입정지)."""
    playbook = "R2_mdd_kill" if is_kill else "R2_mdd_warn"
    allowed, rem = _check_and_mark_cooldown(bot_id, playbook, cooldown_sec=43200, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []
    ex_id = str(cfg.get("EXCHANGE_ID", "")).lower()
    min_cmp = 22.0 if ex_id == "binance" else 18.0

    if cfg.get("USE_AUTO_COMPOUND"):
        cur_cmp = float(cfg.get("AUTO_COMPOUND_PCT", 25.0) or 25.0)
        new_cmp = max(min_cmp, round(cur_cmp * 0.80, 1))
        if new_cmp < cur_cmp - 0.5:
            prev_values["AUTO_COMPOUND_PCT"] = orig_cfg.get("AUTO_COMPOUND_PCT")
            cfg["AUTO_COMPOUND_PCT"] = new_cmp
            actions.append(f"AUTO_COMPOUND_PCT: {cur_cmp:.1f}%→{new_cmp:.1f}% (MDD 방어 감축)")

    if not cfg.get("USE_DYNAMIC_REGIME", False):
        prev_values["USE_DYNAMIC_REGIME"] = orig_cfg.get("USE_DYNAMIC_REGIME", False)
        cfg["USE_DYNAMIC_REGIME"] = True
        actions.append("USE_DYNAMIC_REGIME: False→True (연패 시드 50% 축소 활성)")

    if _disable_auto_switch(cfg, actions):
        for mk in ("USE_AUTO_MODE_SWITCH", "USE_BLUEFROG", "DASHBOARD_META"):
            if mk in orig_cfg and orig_cfg.get(mk) != cfg.get(mk):
                prev_values[mk] = copy.deepcopy(orig_cfg.get(mk))

    cur_max_pos = int(float(cfg.get("MAX_POSITIONS", 2) or 2))
    target_max_pos = 1 if is_kill else 2
    if cur_max_pos > target_max_pos:
        prev_values["MAX_POSITIONS"] = orig_cfg.get("MAX_POSITIONS")
        cfg["MAX_POSITIONS"] = target_max_pos
        actions.append(f"MAX_POSITIONS: {cur_max_pos}→{target_max_pos}")

    if is_kill and cfg.get("AUTO_TRADING", True):
        prev_values["AUTO_TRADING"] = orig_cfg.get("AUTO_TRADING", True)
        cfg["AUTO_TRADING"] = False
        actions.append("AUTO_TRADING: True→False (Peak-MDD 킬선 초과로 신규 진입 긴급 차단)")

    if not actions:
        return {"applied": False, "skipped": "already_hardened"}

    sev = "CRITICAL" if is_kill else "WARN"
    title = (
        f"Peak-MDD 킬선({peak_dd_pct:.1f}% ≤ -{mdd_kill:.1f}%) 긴급 진입 차단 및 비중 축소"
        if is_kill
        else f"Peak-MDD 주의({peak_dd_pct:.1f}% ≤ -{mdd_warn:.1f}%) 자율 리스크 감축"
    )
    return _apply_and_restart(
        bot_id,
        cwd,
        playbook,
        title,
        actions,
        reason=f"Peak-MDD {peak_dd_pct:.2f}% 도달에 따른 R2 자율 방어",
        cfg_path=cfg_path,
        cfg=cfg,
        severity=sev,
        force_restart_with_pos=is_kill,
        prev_values=prev_values,
        eval_status="skipped_na",
        record_defense_baseline_keys=["AUTO_COMPOUND_PCT", "MAX_POSITIONS", "AUTO_TRADING"],
    )


def _sync_meta_tf(cfg: Dict[str, Any], old_tf: str, new_tf: str) -> None:
    meta = cfg.get("DASHBOARD_META")
    if not isinstance(meta, dict):
        return
    strat = str(meta.get("strategy") or "")
    if f"({old_tf})" in strat:
        meta["strategy"] = strat.replace(f"({old_tf})", f"({new_tf})")


def _sync_meta_be(cfg: Dict[str, Any], new_be_pct: float) -> None:
    meta = cfg.get("DASHBOARD_META")
    if not isinstance(meta, dict):
        return
    pct_txt = f"+{new_be_pct * 100:.1f}%"
    for k in ("indicators", "tp_str"):
        val = str(meta.get(k) or "")
        if val:
            val = re.sub(r"본절\(\+?[0-9.]+%\)", f"본절({pct_txt})", val)
            val = re.sub(r"BE\s*\(\+?[0-9.]+%\)", f"BE({pct_txt})", val)
            val = re.sub(r"BE\s*\+[0-9.]+%", f"BE {pct_txt}", val)
            meta[k] = val


def remediate_fee_or_alpha_decay(
    bot_id: str,
    cwd: str,
    reason_tag: str,
    closed_all: int,
    sample_days: float = 0.0,
) -> Dict[str, Any]:
    """[Playbook R3] 누적 수수료 적자 / 알파 감쇠 시 단계적 파라미터·타임프레임 자율 튜닝 (24h 쿨다운)."""
    if closed_all < 20:
        return {"applied": False, "skipped": "insufficient_trades"}

    allowed, rem = _check_and_mark_cooldown(bot_id, "R3_alpha_tune", cooldown_sec=86400, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    base_metrics = _compute_window_metrics(cwd, last_n=20)
    prev_values: Dict[str, Any] = {}
    block_sigs: List[str] = []
    actions: List[str] = []

    cur_tf = str(cfg.get("TIMEFRAME") or "1h").strip()
    ts_act = float(cfg.get("TRAILING_ACTIVATE_PCT", 0.03) or 0.03)
    cur_be = float(cfg.get("BE_GUARD_TRIGGER_PCT", 0.0) or 0.0)
    safe_be_cap = min(0.022, round(max(cur_be, ts_act - 0.002), 3))

    # Bounded 1-step tuning ladder (1 step per 24h max, skipping R8-blocked steps)
    if cur_tf in ("5m", "15m") and not _is_action_blocked(bot_id, "R3_alpha_tune:TIMEFRAME"):
        next_tf = "15m" if cur_tf == "5m" else "1h"
        prev_values["TIMEFRAME"] = orig_cfg.get("TIMEFRAME")
        if "DASHBOARD_META" in orig_cfg:
            prev_values["DASHBOARD_META"] = copy.deepcopy(orig_cfg["DASHBOARD_META"])
        cfg["TIMEFRAME"] = next_tf
        _sync_meta_tf(cfg, cur_tf, next_tf)
        block_sigs.append("TIMEFRAME")
        actions.append(f"TIMEFRAME: {cur_tf}→{next_tf} (수수료 잠식 완화 및 신호 품질 상향)")
    elif cfg.get("USE_AUTO_MODE_SWITCH") and not _is_action_blocked(
        bot_id, "R3_alpha_tune:USE_AUTO_MODE_SWITCH"
    ):
        if _disable_auto_switch(cfg, actions):
            for mk in ("USE_AUTO_MODE_SWITCH", "USE_BLUEFROG", "DASHBOARD_META"):
                if mk in orig_cfg and orig_cfg.get(mk) != cfg.get(mk):
                    prev_values[mk] = copy.deepcopy(orig_cfg.get(mk))
            block_sigs.append("USE_AUTO_MODE_SWITCH")
    elif (
        "BE_GUARD_TRIGGER_PCT" in cfg
        and cur_be < safe_be_cap - 1e-4
        and not _is_action_blocked(bot_id, "R3_alpha_tune:BE_GUARD_TRIGGER_PCT")
    ):
        prev_values["BE_GUARD_TRIGGER_PCT"] = orig_cfg.get("BE_GUARD_TRIGGER_PCT")
        if "DASHBOARD_META" in orig_cfg:
            prev_values["DASHBOARD_META"] = copy.deepcopy(orig_cfg["DASHBOARD_META"])
        cfg["BE_GUARD_TRIGGER_PCT"] = safe_be_cap
        _sync_meta_be(cfg, safe_be_cap)
        block_sigs.append("BE_GUARD_TRIGGER_PCT")
        actions.append(f"BE_GUARD_TRIGGER_PCT: +{cur_be*100:.1f}%→+{safe_be_cap*100:.1f}% (미세 본절청산 방지)")
    else:
        changed = False
        cur_cd = float(cfg.get("COOLDOWN_HOURS", 4.0) or 4.0)
        if cur_cd < 6.0 and not _is_action_blocked(bot_id, "R3_alpha_tune:COOLDOWN_HOURS"):
            prev_values["COOLDOWN_HOURS"] = orig_cfg.get("COOLDOWN_HOURS")
            cfg["COOLDOWN_HOURS"] = 6.0
            block_sigs.append("COOLDOWN_HOURS")
            actions.append(f"COOLDOWN_HOURS: {cur_cd:.1f}h→6.0h (연패 재진입 억제)")
            changed = True
        cur_mp = int(float(cfg.get("MAX_POSITIONS", 2) or 2))
        if cur_mp > 1 and not _is_action_blocked(bot_id, "R3_alpha_tune:MAX_POSITIONS"):
            prev_values["MAX_POSITIONS"] = orig_cfg.get("MAX_POSITIONS")
            cfg["MAX_POSITIONS"] = cur_mp - 1
            block_sigs.append("MAX_POSITIONS")
            actions.append(f"MAX_POSITIONS: {cur_mp}→{cur_mp - 1} (저품질 동시진입 축소)")
            changed = True
        if (
            not changed
            and cfg.get("AUTO_COMPOUND_PCT")
            and not _is_action_blocked(bot_id, "R3_alpha_tune:AUTO_COMPOUND_PCT")
        ):
            ex_id = str(cfg.get("EXCHANGE_ID", "")).lower()
            min_cmp = 22.0 if ex_id == "binance" else 18.0
            cur_cmp = float(cfg.get("AUTO_COMPOUND_PCT", 25.0) or 25.0)
            if cur_cmp > min_cmp + 1.0:
                new_cmp = max(min_cmp, round(cur_cmp * 0.85, 1))
                prev_values["AUTO_COMPOUND_PCT"] = orig_cfg.get("AUTO_COMPOUND_PCT")
                cfg["AUTO_COMPOUND_PCT"] = new_cmp
                block_sigs.append("AUTO_COMPOUND_PCT")
                actions.append(f"AUTO_COMPOUND_PCT: {cur_cmp:.1f}%→{new_cmp:.1f}% (적자 방어 비중 축소)")
                changed = True
        if not changed:
            return {"applied": False, "skipped": "no_further_safe_tuning"}

    def_keys = [k for k in ("AUTO_COMPOUND_PCT", "MAX_POSITIONS") if k in prev_values]
    return _apply_and_restart(
        bot_id,
        cwd,
        "R3_alpha_tune",
        f"수익성/수수료 방어 자율 튜닝 ({reason_tag})",
        actions,
        reason=f"{reason_tag} (청산 {closed_all}건 / {sample_days:.1f}일)",
        cfg_path=cfg_path,
        cfg=cfg,
        severity="WARN",
        force_restart_with_pos=False,
        prev_values=prev_values,
        baseline_metrics=base_metrics,
        eval_status="pending",
        block_sigs=block_sigs,
        record_defense_baseline_keys=def_keys or None,
    )


def remediate_config_gaps(
    bot_id: str, cwd: str, thresholds: Dict[str, Any], ref_cap: float
) -> Dict[str, Any]:
    """[Playbook R4] 생존 설정(MAX_DRAWDOWN_PCT, DAILY_LOSS_LIMIT_USDT, USE_DYNAMIC_REGIME) 자동 복구."""
    allowed, rem = _check_and_mark_cooldown(bot_id, "R4_config_gap", cooldown_sec=43200, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []
    cfg_mdd = float(cfg.get("MAX_DRAWDOWN_PCT", 0.5) or 0.5)
    rec_mdd = float(thresholds.get("recommend_max_drawdown_pct", 0.20))
    if cfg_mdd >= 0.45:
        prev_values["MAX_DRAWDOWN_PCT"] = orig_cfg.get("MAX_DRAWDOWN_PCT")
        cfg["MAX_DRAWDOWN_PCT"] = rec_mdd
        actions.append(f"MAX_DRAWDOWN_PCT: {cfg_mdd:.2f}→{rec_mdd:.2f}")

    cfg_dll = float(cfg.get("DAILY_LOSS_LIMIT_USDT", 999.0) or 999.0)
    if cfg_dll >= 500.0 or cfg_dll > ref_cap * 0.25:
        rec_dll = round(ref_cap * float(thresholds.get("recommend_daily_loss_limit_pct_of_seed", 0.06)), 2)
        prev_values["DAILY_LOSS_LIMIT_USDT"] = orig_cfg.get("DAILY_LOSS_LIMIT_USDT")
        cfg["DAILY_LOSS_LIMIT_USDT"] = rec_dll
        actions.append(f"DAILY_LOSS_LIMIT_USDT: ${cfg_dll:.2f}→${rec_dll:.2f}")

    if bool(thresholds.get("require_dynamic_regime", True)) and not bool(cfg.get("USE_DYNAMIC_REGIME", False)):
        prev_values["USE_DYNAMIC_REGIME"] = orig_cfg.get("USE_DYNAMIC_REGIME", False)
        cfg["USE_DYNAMIC_REGIME"] = True
        actions.append("USE_DYNAMIC_REGIME: False→True")

    if not actions:
        return {"applied": False, "skipped": "no_actionable_gap"}

    return _apply_and_restart(
        bot_id,
        cwd,
        "R4_config_gap",
        "생존 안전장치(config_gap) 자율 복구",
        actions,
        reason="생존 설정 누락 자동 보강",
        cfg_path=cfg_path,
        cfg=cfg,
        severity="WARN",
        force_restart_with_pos=False,
        prev_values=prev_values,
        eval_status="skipped_na",
    )


def _update_history_event_match(
    bot_id: str,
    playbook: str,
    ev_ts: float,
    updates: Dict[str, Any],
    block_keys: Optional[List[str]] = None,
    block_until: float = 0.0,
) -> None:
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
            for ev in doc["events"]:
                if (
                    str(ev.get("bot_id")) == str(bot_id)
                    and ev.get("playbook") == playbook
                    and abs(float(ev.get("ts") or 0.0) - float(ev_ts)) < 1e-3
                ):
                    ev.update(copy.deepcopy(updates))
                    break
            if block_keys and block_until > 0:
                blocked = doc["blocked_actions"]
                for bk in block_keys:
                    blocked[bk] = block_until
            doc["updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _atomic_write_json(HISTORY_FILE, doc)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def evaluate_and_rollback_remediations(bots: List[Any]) -> List[Dict[str, Any]]:
    """[Playbook R8] R3/R10 자율 변경 사후 수익성 검증 및 악화 시 자동 롤백 + 7일 차단."""
    results: List[Dict[str, Any]] = []
    allowed_bots = {str(b) for b in bots}
    now = time.time()

    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
            events_snap = copy.deepcopy(doc["events"])
            pending_restarts_snap = copy.deepcopy(doc["pending_restarts"])
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    for ev in events_snap:
        bid = str(ev.get("bot_id") or "")
        pb = str(ev.get("playbook") or "")
        if bid not in allowed_bots:
            continue
        if ev.get("eval_status") != "pending":
            continue
        if pb not in ("R3_alpha_tune", "R10_symbol_prune"):
            continue
        prev_vals = ev.get("prev_values")
        if not isinstance(prev_vals, dict) or not prev_vals:
            continue
        if bid in pending_restarts_snap:
            continue

        cwd = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(cwd, ".stopped")):
            continue

        since_ts = float(ev.get("activated_ts") or ev.get("ts") or 0.0)
        if since_ts <= 0:
            continue
        age_sec = max(0.0, now - since_ts)
        post = _compute_window_metrics(cwd, since_ts=since_ts)

        if post["trades"] < R8_MIN_POST_TRADES:
            if age_sec >= R8_EXPIRE_SEC and post["trades"] < R8_MIN_TRADES_AFTER_WAIT:
                _update_history_event_match(
                    bid, pb, float(ev["ts"]),
                    {"eval_status": "expired_low_sample", "post_metrics": post, "eval_detail": "14일 표본 부족 만료"},
                )
                results.append({"bot_id": bid, "playbook": pb, "status": "expired_low_sample"})
                continue
            if not (age_sec >= R8_MAX_WAIT_SEC and post["trades"] >= R8_MIN_TRADES_AFTER_WAIT):
                continue

        base = ev.get("baseline_metrics") or {}
        base_exp = _safe_float(base.get("expectancy"), 0.0)
        base_pf = _safe_float(base.get("pf"), 1.0)
        base_n = int(base.get("trades") or 0)

        if base_n > 0:
            degraded = (
                post["expectancy"] < base_exp - 0.005
                and (post["pf"] < max(base_pf, 1.0) or post["net_pnl"] < -0.15)
            )
        else:
            degraded = post["net_pnl"] < -0.15 and post["pf"] < 0.85

        if degraded:
            cfg_path, cfg = _load_bot_config_with_backup(cwd)
            if not cfg:
                continue
            restored_actions: List[str] = []
            for k, old_v in prev_vals.items():
                cur_v = cfg.get(k)
                cfg[k] = copy.deepcopy(old_v)
                if k == "SYMBOL_WHITELIST" and isinstance(old_v, list) and isinstance(cur_v, list):
                    restored_actions.append(f"SYMBOL_WHITELIST: {len(cur_v)}종목→{len(old_v)}종목 복원")
                elif k != "DASHBOARD_META":
                    restored_actions.append(f"{k}: {cur_v}→{old_v} (원복)")

            _save_bot_config_with_backup(cfg_path, cfg)
            rb_title = f"⏪ [8888 자율 롤백 완료] {pb} 성과 악화로 원복"
            _sync_ver_md(cwd, rb_title, restored_actions)

            has_pos = _should_hold_restart_for_positions(cwd)
            restarted = False
            if not has_pos:
                ok, detail = bot_restart_locked(
                    bid, cwd, source="aegis_v8_R8_auto_rollback", reason=rb_title, cooldown_sec=60
                )
                restarted = bool(ok)
                if restarted:
                    restored_actions.append(f"엔진 안전 재기동 완료 ({detail})")
                else:
                    restored_actions.append(f"설정 원복 반영 (재기동 보류: {detail})")
            else:
                restored_actions.append("설정 원복 반영 (보유 포지션 보호로 재기동 유예)")

            _update_pending_restart(bid, restarted, "R8_auto_rollback", rb_title, cwd)

            sigs = [f"{bid}:{pb}:{s}" for s in (ev.get("block_sigs") or [])]
            eval_detail = (
                f"성과 악화(PF {post['pf']:.2f}, Exp ${post['expectancy']:+.4f}, "
                f"Net ${post['net_pnl']:+.2f}) → 자동 롤백"
            )
            _update_history_event_match(
                bid, pb, float(ev["ts"]),
                {"eval_status": "rolled_back", "post_metrics": post, "eval_detail": eval_detail},
                block_keys=sigs,
                block_until=now + R8_BLOCK_SEC,
            )
            _append_history_event(
                bid,
                "R8_auto_rollback",
                rb_title,
                restored_actions,
                reason=f"사후 {post['trades']}건 검증: PF {post['pf']:.2f}, 순손익 ${post['net_pnl']:+.2f} (기준 Exp ${base_exp:+.4f} → ${post['expectancy']:+.4f})",
                severity="WARN",
                notify_discord=True,
                extra={"eval_status": "skipped_na", "rolled_back_from_ts": ev["ts"]},
            )
            results.append({"bot_id": bid, "playbook": pb, "status": "rolled_back", "post": post})
        else:
            status = (
                "verified_improved"
                if (post["expectancy"] >= base_exp or post["net_pnl"] >= 0.0)
                else "verified_neutral"
            )
            eval_detail = (
                f"사후 {post['trades']}건 검증({status}): 승률 {post['win_rate']:.1f}%, "
                f"PF {post['pf']:.2f}, Net ${post['net_pnl']:+.2f}"
            )
            _update_history_event_match(
                bid, pb, float(ev["ts"]),
                {"eval_status": status, "post_metrics": post, "eval_detail": eval_detail},
            )
            if status == "verified_improved":
                send_autonomous_action_report(
                    bid,
                    f"자율 튜닝({pb}) 성과 검증 통과",
                    [
                        f"사후 {post['trades']}건: 승률 {post['win_rate']:.1f}%, PF {post['pf']:.2f}, 순손익 ${post['net_pnl']:+.2f} (기대값 ${post['expectancy']:+.4f}/건)"
                    ],
                    reason=f"기준 기대값 ${base_exp:+.4f} → 사후 ${post['expectancy']:+.4f} 유지 확정",
                    severity="INFO",
                )
            results.append({"bot_id": bid, "playbook": pb, "status": status, "post": post})

    return results


def remediate_recovery_scale_up(
    bot_id: str,
    cwd: str,
    abs_peak_dd: Optional[float],
    mdd_warn: float,
) -> Dict[str, Any]:
    """[Playbook R9] R2/R3 방어 축소 후 수익·MDD 회복 확인 시 원래 기준치로 단계적 복구 스케일업."""
    allowed, rem = _check_and_mark_cooldown(bot_id, "R9_recovery_scale_up", cooldown_sec=86400, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
            base = copy.deepcopy(doc["pre_defense_baseline"].get(str(bot_id)) or {})
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    if not base:
        return {"applied": False, "skipped": "no_defense_baseline"}

    if abs_peak_dd is None or abs_peak_dd >= mdd_warn * 0.65:
        return {"applied": False, "skipped": "mdd_not_recovered"}

    recent = _compute_window_metrics(cwd, last_n=10)
    if recent["trades"] < 8 or recent["pf"] < 1.3 or recent["net_pnl"] <= 0.0:
        return {"applied": False, "skipped": "recent_profit_insufficient"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []

    if "AUTO_COMPOUND_PCT" in base:
        base_cmp = float(base["AUTO_COMPOUND_PCT"])
        cur_cmp = float(cfg.get("AUTO_COMPOUND_PCT", base_cmp) or base_cmp)
        if cur_cmp < base_cmp - 0.5:
            step = max(2.0, round((base_cmp - cur_cmp) * 0.5, 1))
            new_cmp = min(base_cmp, round(cur_cmp + step, 1))
            prev_values["AUTO_COMPOUND_PCT"] = orig_cfg.get("AUTO_COMPOUND_PCT")
            cfg["AUTO_COMPOUND_PCT"] = new_cmp
            actions.append(f"AUTO_COMPOUND_PCT: {cur_cmp:.1f}%→{new_cmp:.1f}% (회복 단계 상향, 목표 {base_cmp:.1f}%)")

    if "MAX_POSITIONS" in base:
        base_mp = int(float(base["MAX_POSITIONS"]))
        cur_mp = int(float(cfg.get("MAX_POSITIONS", base_mp) or base_mp))
        if cur_mp < base_mp:
            new_mp = min(base_mp, cur_mp + 1)
            prev_values["MAX_POSITIONS"] = orig_cfg.get("MAX_POSITIONS")
            cfg["MAX_POSITIONS"] = new_mp
            actions.append(f"MAX_POSITIONS: {cur_mp}→{new_mp} (목표 {base_mp})")

    if base.get("AUTO_TRADING") is True and cfg.get("AUTO_TRADING") is False and abs_peak_dd < mdd_warn * 0.50:
        prev_values["AUTO_TRADING"] = False
        cfg["AUTO_TRADING"] = True
        actions.append("AUTO_TRADING: False→True (회복 확인으로 자동 진입 재개)")

    if not actions:
        with open(HISTORY_LOCK, "w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
                if str(bot_id) in doc["pre_defense_baseline"]:
                    doc["pre_defense_baseline"].pop(str(bot_id), None)
                    _atomic_write_json(HISTORY_FILE, doc)
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        return {"applied": False, "skipped": "already_at_baseline"}

    res = _apply_and_restart(
        bot_id,
        cwd,
        "R9_recovery_scale_up",
        "수익 회복 확인 — 방어 축소 비중 단계적 복구",
        actions,
        reason=(
            f"Peak-MDD {abs_peak_dd:.1f}% (<{mdd_warn*0.65:.1f}%) 및 "
            f"최근 {recent['trades']}건 PF {recent['pf']:.2f} / 순손익 ${recent['net_pnl']:+.2f}"
        ),
        cfg_path=cfg_path,
        cfg=cfg,
        severity="INFO",
        force_restart_with_pos=False,
        prev_values=prev_values,
        eval_status="skipped_na",
    )

    fully_restored = True
    if "AUTO_COMPOUND_PCT" in base and float(cfg.get("AUTO_COMPOUND_PCT", 0) or 0) < float(base["AUTO_COMPOUND_PCT"]) - 0.5:
        fully_restored = False
    if "MAX_POSITIONS" in base and int(float(cfg.get("MAX_POSITIONS", 0) or 0)) < int(float(base["MAX_POSITIONS"])):
        fully_restored = False
    if base.get("AUTO_TRADING") is True and not bool(cfg.get("AUTO_TRADING", True)):
        fully_restored = False
    if fully_restored:
        with open(HISTORY_LOCK, "w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
                doc["pre_defense_baseline"].pop(str(bot_id), None)
                _atomic_write_json(HISTORY_FILE, doc)
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    return res


def remediate_bleeding_symbols(bot_id: str, cwd: str) -> Dict[str, Any]:
    """[Playbook R10] 최근 14일 만성 손실 종목 화이트리스트 자율 제외 (최소 16종목·보유포지션 보호)."""
    allowed, rem = _check_and_mark_cooldown(bot_id, "R10_symbol_prune", cooldown_sec=86400, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    wl = cfg.get("SYMBOL_WHITELIST")
    if not isinstance(wl, list) or len(wl) <= MIN_WHITELIST_SIZE:
        return {"applied": False, "skipped": "whitelist_at_floor"}

    act = _load_json(os.path.join(cwd, "data", "active_positions.json"), {})
    open_syms = set(act.keys()) if isinstance(act, dict) else set()

    cutoff_14d = time.time() - 14 * 86400
    all_fee_rows, closes = _read_bot_trade_rows(cwd)

    sym_stats: Dict[str, Dict[str, Any]] = {}
    for c in closes:
        if c["ts"] < cutoff_14d:
            continue
        sym = c["symbol"]
        st = sym_stats.setdefault(sym, {"trades": 0, "wins": 0, "gross_pnl": 0.0, "fees": 0.0})
        st["trades"] += 1
        if c["pnl"] > 0:
            st["wins"] += 1
        st["gross_pnl"] += c["pnl"]

    for r in all_fee_rows:
        if r["ts"] < cutoff_14d:
            continue
        sym = r["symbol"]
        if sym in sym_stats:
            sym_stats[sym]["fees"] += r["fee"]

    wl_set = set(wl)
    candidates: List[Dict[str, Any]] = []
    for sym, st in sym_stats.items():
        if sym not in wl_set or sym in open_syms:
            continue
        if _is_action_blocked(bot_id, f"R10_symbol_prune:{sym}"):
            continue
        trades = st["trades"]
        if trades < 4:
            continue
        wr = st["wins"] / trades
        net_pnl = round(st["gross_pnl"] - st["fees"], 4)
        if wr <= 0.20 and net_pnl <= -0.30:
            candidates.append({"symbol": sym, "trades": trades, "wr_pct": round(wr * 100.0, 1), "net_pnl": net_pnl})

    if not candidates:
        return {"applied": False, "skipped": "no_bleeding_symbols"}

    candidates.sort(key=lambda x: x["net_pnl"])
    max_prune = min(2, len(wl) - MIN_WHITELIST_SIZE)
    if max_prune <= 0:
        return {"applied": False, "skipped": "whitelist_at_floor"}
    chosen = candidates[:max_prune]
    prune_set = {c["symbol"] for c in chosen}

    prev_values = {"SYMBOL_WHITELIST": list(wl)}
    base_metrics = _compute_window_metrics(cwd, last_n=20)
    block_sigs = [c["symbol"] for c in chosen]
    cfg["SYMBOL_WHITELIST"] = [s for s in wl if s not in prune_set]

    detail_str = ", ".join(
        f"{c['symbol']}({c['trades']}건/승률{c['wr_pct']:.0f}%/순${c['net_pnl']:+.2f})"
        for c in chosen
    )
    actions = [
        f"SYMBOL_WHITELIST: {len(wl)}종목→{len(cfg['SYMBOL_WHITELIST'])}종목",
        f"제외 종목: {detail_str}",
    ]
    return _apply_and_restart(
        bot_id,
        cwd,
        "R10_symbol_prune",
        f"만성 손실 종목 {len(chosen)}개 화이트리스트 자율 제외",
        actions,
        reason=f"최근 14일 만성 손실(>=4건·승률<=20%·순손실<=-$0.30): {detail_str}",
        cfg_path=cfg_path,
        cfg=cfg,
        severity="WARN",
        force_restart_with_pos=False,
        prev_values=prev_values,
        baseline_metrics=base_metrics,
        eval_status="pending",
        block_sigs=block_sigs,
    )


def flush_pending_restarts(bots: List[Any]) -> List[Dict[str, Any]]:
    """[Deferred Apply] 보유 포지션 청산 확인 시 유예된 config 변경 재기동을 즉시 완결한다."""
    completed: List[Dict[str, Any]] = []
    allowed_bots = {str(b) for b in bots}

    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
            pend_snap = copy.deepcopy(doc["pending_restarts"])
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    for bid, info in pend_snap.items():
        if str(bid) not in allowed_bots:
            continue
        info = info if isinstance(info, dict) else {}
        cwd = str(info.get("cwd") or os.path.join(BASE_PROJECT, str(bid)))
        if os.path.exists(os.path.join(cwd, ".stopped")):
            with open(HISTORY_LOCK, "w") as lf:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
                    doc["pending_restarts"].pop(str(bid), None)
                    _atomic_write_json(HISTORY_FILE, doc)
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            continue

        if _should_hold_restart_for_positions(cwd):
            continue

        pb = str(info.get("playbook") or "deferred")
        ok, detail = bot_restart_locked(
            str(bid), cwd, source="aegis_v8_deferred_apply", reason=f"지연 설정 자동 반영({pb})", cooldown_sec=60
        )
        if ok:
            now = time.time()
            with open(HISTORY_LOCK, "w") as lf:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
                    doc["pending_restarts"].pop(str(bid), None)
                    for ev in doc["events"]:
                        if (
                            str(ev.get("bot_id")) == str(bid)
                            and ev.get("eval_status") == "pending"
                            and not ev.get("activated_ts")
                        ):
                            ev["activated_ts"] = now
                    _atomic_write_json(HISTORY_FILE, doc)
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

            _append_history_event(
                str(bid),
                "deferred_apply",
                f"🔄 지연 설정 자동 반영 완료 ({pb})",
                [f"포지션 청산 확인 → 안전 재기동 완료 ({detail})"],
                reason=str(info.get("reason") or "보유 포지션 청산 후 지연 설정 반영"),
                severity="INFO",
                notify_discord=True,
                extra={"eval_status": "skipped_na"},
            )
            completed.append({"bot_id": str(bid), "playbook": pb, "detail": detail})

    return completed

