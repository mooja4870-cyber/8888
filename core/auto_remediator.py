"""
core/auto_remediator.py — Aegis V9 Full Autonomous Alert Remediation 자율 적기 조치 엔진 (보스 위임 2026-11-27)

워치독 감시 활동에서 포착된 모든 문제점 및 선제 경보에 대해 보스 사전 승인 대기 없이
안전한 클램프·쿨다운·사전 백업(.auto_bak)·공유 락 재기동(bot_restart_locked)·
디스코드 사후 보고·사후 수익성 검증 및 자동 롤백을 결합하여 수익성 향상 방향으로 자율 조치를 수행한다.

Playbooks:
  - R1: 진입 사이징/최소명목가 오류(NOTIONAL_MIN_ERROR 등) 자동 보정 (6h 쿨다운)
  - R2: Peak-MDD 주의/킬선 도달 시 자동 비중 축소·방향고정·킬선 진입정지 (12h 쿨다운)
  - R3: 수수료 적자/조기 알파 감쇠 시 단계적 파라미터·타임프레임 자율 튜닝 (24h 쿨다운)
  - R4: 생존 설정 누락(config_gap) 자동 복구 (12h 쿨다운)
  - R8: R3/R10 자율 변경 사후 수익성 검증 및 성과 악화 시 자동 롤백 + 7일 재적용 차단
  - R9: R2/R3/R11/R14 방어 축소 이후 수익 회복 시 원래 기준치까지 단계적 복구 스케일업 (24h 쿨다운)
  - R10: 최근 14일 만성 손실 종목 화이트리스트 자율 제외 (최소 16종목·보유포지션 보호, 24h 쿨다운)
  - R11: 연패(WARN/CRITICAL)·수수료 주의 시 동적비중/쿨다운/동시보유·R3 자율 방어
  - R12: .env 권한(chmod 600), 손상 JSON 복원, 좀비 스크립트 정리, 디스크 청소, 메모리/FD/피드 동결 재기동
  - R13: 상장폐지·레버리지 상한 하향·과다 펀딩비 자율 방어
  - R14: 포트폴리오 쏠림·24h 급락·USDT 디페깅·BTC 쇼크 시 전 봇 단계적 방어 및 회복 후 R9 복구
  - R15: TCA 체결품질 저하 R3 연계 및 OTR 주문 폭주 즉시 제어
  - R16: AI 14대 자율감사 이상 자동 완결 및 중복 경보 억제
  - Deferred Apply: 보유 포지션 청산 직후 유예된 config 재기동 자동 완결
  - Helper: 외부 모듈(bot_sentinel R6/R7, autonomous_auditor R5/R16) 이력 기록 및 보고
"""
import copy
import csv
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
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

EXTERNAL_ONLY_ALERT_PREFIXES = (
    "infra_api_auth_error",
    "infra_api_key_expiry",
    "infra_exchange_maintenance",
    "infra_clock_latency_",
    "host_external_network_down",
    "host_public_ip_changed",
    "host_ac_sleep_enabled",
    "host_mac_sleep_wake",
    "canary_",
)


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
        if pb not in ("R3_alpha_tune", "R10_symbol_prune", "R18_mae_mfe_tune", "R21_dir_skew", "R23_shadow_relax"):
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Aegis V9 Playbooks R11 ~ R15 + Universal Alert Dispatcher
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def remediate_loss_streak_or_fee_warn(
    bot_id: str,
    cwd: str,
    reason_tag: str,
    is_kill: bool = False,
    is_fee_warn: bool = False,
    closed_all: int = 0,
) -> Dict[str, Any]:
    """[Playbook R11] 연패(주의/킬선) 및 수수료 비중 주의(WARN) 시 자율 방어·튜닝."""
    if is_fee_warn:
        return remediate_fee_or_alpha_decay(
            bot_id, cwd, reason_tag, closed_all=max(int(closed_all or 0), 20)
        )

    playbook = "R11_loss_streak_kill" if is_kill else "R11_loss_streak_warn"
    allowed, rem = _check_and_mark_cooldown(bot_id, playbook, cooldown_sec=43200, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []

    if not cfg.get("USE_DYNAMIC_REGIME", False):
        prev_values["USE_DYNAMIC_REGIME"] = False
        cfg["USE_DYNAMIC_REGIME"] = True
        actions.append("USE_DYNAMIC_REGIME: False→True (연패 시드 50% 축소 활성)")

    if _disable_auto_switch(cfg, actions):
        for mk in ("USE_AUTO_MODE_SWITCH", "USE_BLUEFROG", "DASHBOARD_META"):
            if mk in orig_cfg and orig_cfg.get(mk) != cfg.get(mk):
                prev_values[mk] = copy.deepcopy(orig_cfg.get(mk))

    cur_cd = float(cfg.get("COOLDOWN_HOURS", 4.0) or 4.0)
    if cur_cd < 6.0:
        prev_values["COOLDOWN_HOURS"] = orig_cfg.get("COOLDOWN_HOURS")
        cfg["COOLDOWN_HOURS"] = 6.0
        actions.append(f"COOLDOWN_HOURS: {cur_cd:.1f}h→6.0h (연패 과매매 억제)")

    if is_kill:
        cur_mp = int(float(cfg.get("MAX_POSITIONS", 2) or 2))
        if cur_mp > 1:
            prev_values["MAX_POSITIONS"] = orig_cfg.get("MAX_POSITIONS")
            cfg["MAX_POSITIONS"] = 1
            actions.append(f"MAX_POSITIONS: {cur_mp}→1 (최대 연패 방어)")

        if cfg.get("USE_AUTO_COMPOUND"):
            ex_id = str(cfg.get("EXCHANGE_ID", "")).lower()
            min_cmp = 22.0 if ex_id == "binance" else 18.0
            cur_cmp = float(cfg.get("AUTO_COMPOUND_PCT", 25.0) or 25.0)
            new_cmp = max(min_cmp, round(cur_cmp * 0.80, 1))
            if new_cmp < cur_cmp - 0.5:
                prev_values["AUTO_COMPOUND_PCT"] = orig_cfg.get("AUTO_COMPOUND_PCT")
                cfg["AUTO_COMPOUND_PCT"] = new_cmp
                actions.append(f"AUTO_COMPOUND_PCT: {cur_cmp:.1f}%→{new_cmp:.1f}% (연패 킬선 비중 감축)")

    if not actions:
        return {"applied": False, "skipped": "already_hardened"}

    sev = "CRITICAL" if is_kill else "WARN"
    title = (
        f"최대 연패 임계 방어 자율 조치 ({reason_tag})"
        if is_kill
        else f"연패 주의 구간 자율 방어 ({reason_tag})"
    )
    return _apply_and_restart(
        bot_id,
        cwd,
        playbook,
        title,
        actions,
        reason=f"{reason_tag} 감지에 따른 R11 자율 리스크 축소",
        cfg_path=cfg_path,
        cfg=cfg,
        severity=sev,
        force_restart_with_pos=False,
        prev_values=prev_values,
        eval_status="skipped_na",
        record_defense_baseline_keys=["AUTO_COMPOUND_PCT", "MAX_POSITIONS"],
    )


def remediate_infra_or_security_alert(alert: Dict[str, Any], bots: List[Any]) -> Dict[str, Any]:
    """[Playbook R12] .env 권한 600, 손상 JSON 복원, 좀비 정리, 디스크 청소, 메모리/FD/피드 동결 재기동."""
    bid = str(alert.get("bot_id") or "8888")
    key = str(alert.get("key") or "")
    sev = str(alert.get("severity") or "WARN").upper()
    details = str(alert.get("details") or "")
    allowed_bots = {str(b) for b in bots}

    # a) .env permission hardening
    if key in ("security_env_writable", "security_env_readable"):
        env_path = os.path.join(BASE_8888, ".env") if bid == "8888" else os.path.join(BASE_PROJECT, bid, ".env")
        if not os.path.exists(env_path):
            return {"applied": False, "skipped": "env_missing"}
        try:
            mode = os.stat(env_path).st_mode & 0o777
            if (mode & 0o066) == 0:
                return {"applied": False, "skipped": "already_600", "suppress_alert": (sev == "INFO")}
            os.chmod(env_path, 0o600)
            act = [f"chmod 600 {env_path} ({oct(mode)[2:]}→600)"]
            _append_history_event(
                bid,
                "R12_env_chmod",
                ".env API 키 파일 권한 600 자율 복구",
                act,
                reason=details or f".env 권한 {oct(mode)[2:]} 감지",
                severity="INFO",
                notify_discord=(sev == "CRITICAL"),
                extra={"eval_status": "skipped_na"},
            )
            return {"applied": True, "actions": act, "suppress_alert": (sev == "INFO")}
        except Exception as exc:
            return {"applied": False, "skipped": f"chmod_err:{exc}"}

    # b) JSON corruption auto-restore from backups
    if key == "security_json_corrupted":
        if bid not in allowed_bots:
            return {"applied": False, "skipped": "unsupported_target"}
        allowed, rem = _check_and_mark_cooldown(bid, "R12_json_restore", cooldown_sec=3600, dry_run=True)
        if not allowed:
            return {"applied": False, "skipped": f"cooldown_{rem}s"}
        cwd = os.path.join(BASE_PROJECT, bid)
        restored: List[str] = []
        backup_root = os.path.join(BASE_8888, "backups")
        for rel in ("config.json", "data/stats.json", "data/active_positions.json"):
            jp = os.path.join(cwd, rel)
            if not os.path.exists(jp):
                continue
            try:
                with open(jp, "r", encoding="utf-8") as f:
                    json.load(f)
                continue
            except Exception:
                pass

            cands = [jp + ".auto_bak", jp + ".bak"]
            if os.path.isdir(backup_root):
                for day_dir in sorted(os.listdir(backup_root), reverse=True):
                    cands.append(os.path.join(backup_root, day_dir, bid, os.path.basename(rel)))
            for cand in cands:
                if not os.path.exists(cand):
                    continue
                try:
                    with open(cand, "r", encoding="utf-8") as cf:
                        json.load(cf)
                    tmp = f"{jp}.restore.{os.getpid()}"
                    shutil.copy2(cand, tmp)
                    os.replace(tmp, jp)
                    restored.append(f"{rel} 자동 복원 ({os.path.basename(cand)})")
                    break
                except Exception:
                    continue

        if not restored:
            return {"applied": False, "skipped": "no_valid_backup"}

        has_pos = _should_hold_restart_for_positions(cwd)
        restarted = False
        if not has_pos:
            ok, detail = bot_restart_locked(
                bid, cwd, source="aegis_v9_R12_json_restore", reason="손상 JSON 복원 후 안전 재기동", cooldown_sec=60
            )
            restarted = bool(ok)
            if restarted:
                restored.append(f"엔진 안전 재기동 완료 ({detail})")
        _update_pending_restart(bid, restarted, "R12_json_restore", "손상 JSON 복원", cwd)
        _append_history_event(
            bid,
            "R12_json_restore",
            "손상 JSON 백업 자동 복원",
            restored,
            reason=details or "JSON 구문 손상 감지",
            severity="WARN",
            notify_discord=True,
            extra={"eval_status": "skipped_na"},
        )
        return {"applied": True, "actions": restored}

    # c) Orphan helper processes cleanup
    if key == "infra_orphan_helpers":
        allowed, rem = _check_and_mark_cooldown("8888", "R12_orphan_cleanup", cooldown_sec=1800, dry_run=True)
        if not allowed:
            return {"applied": False, "skipped": f"cooldown_{rem}s"}
        pids = re.findall(r"PID\s+(\d+)", details)
        killed: List[str] = []
        for pid_s in pids:
            try:
                cmd = subprocess.check_output(["ps", "-p", pid_s, "-o", "command="], text=True, timeout=3).strip()
                if "/Users/l/project/8888/lab/" in cmd or "/tmp/test_" in cmd:
                    os.kill(int(pid_s), signal.SIGTERM)
                    killed.append(f"PID {pid_s} 종료 ({cmd.split()[-1]})")
            except Exception:
                continue
        if not killed:
            return {"applied": False, "skipped": "no_safe_orphan_pid"}
        _append_history_event(
            "8888",
            "R12_orphan_cleanup",
            f"장기 상주 보조 스크립트 {len(killed)}건 자율 종료",
            killed,
            reason=details,
            severity="INFO",
            notify_discord=True,
            extra={"eval_status": "skipped_na"},
        )
        return {"applied": True, "actions": killed}

    # d) Disk cleanup
    if key == "infra_disk_full":
        allowed, rem = _check_and_mark_cooldown("8888", "R12_disk_cleanup", cooldown_sec=21600, dry_run=True)
        if not allowed:
            return {"applied": False, "skipped": f"cooldown_{rem}s"}
        freed_bytes = 0
        actions: List[str] = []
        try:
            for fn in os.listdir(BASE_8888):
                if fn.endswith((".log.2", ".log.3")):
                    fp = os.path.join(BASE_8888, fn)
                    freed_bytes += os.path.getsize(fp)
                    os.remove(fp)
        except Exception:
            pass
        backup_root = os.path.join(BASE_8888, "backups")
        if os.path.isdir(backup_root):
            cutoff = (dt.datetime.now() - dt.timedelta(days=7)).strftime("%Y-%m-%d")
            for name in sorted(os.listdir(backup_root)):
                if re.match(r"^\d{4}-\d{2}-\d{2}$", name) and name < cutoff:
                    full = os.path.join(backup_root, name)
                    if os.path.isdir(full):
                        try:
                            for root, _, files in os.walk(full):
                                for ff in files:
                                    freed_bytes += os.path.getsize(os.path.join(root, ff))
                            shutil.rmtree(full)
                        except Exception:
                            pass
        for b in allowed_bots:
            bak_lp = os.path.join(BASE_PROJECT, b, "bot_engine.log.bak")
            try:
                if os.path.exists(bak_lp) and os.path.getsize(bak_lp) > 10 * 1024 * 1024:
                    freed_bytes += os.path.getsize(bak_lp)
                    os.remove(bak_lp)
            except Exception:
                pass
        if freed_bytes <= 0:
            return {"applied": False, "skipped": "no_reclaimable_files"}
        actions.append(f"구형 로그·백업 자동 정리 ({freed_bytes / (1024 * 1024):.1f}MB 확보)")
        _append_history_event(
            "8888",
            "R12_disk_cleanup",
            "디스크 용량 확보 자율 청소",
            actions,
            reason=details,
            severity="WARN",
            notify_discord=True,
            extra={"eval_status": "skipped_na"},
        )
        return {"applied": True, "actions": actions}

    # e) Memory leak / FD leak / Frozen feed / Stale scan -> safe restart (or defer)
    if key in ("infra_memory_leak", "infra_fd_leak", "feed_stale_scan", "feed_frozen_prices"):
        if key in ("infra_memory_leak", "feed_stale_scan", "feed_frozen_prices") and sev != "CRITICAL":
            return {"applied": False, "skipped": f"{sev.lower()}_monitoring"}
        if bid not in allowed_bots:
            return {"applied": False, "skipped": "non_bot_target"}
        cwd = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(cwd, ".stopped")):
            return {"applied": False, "skipped": "bot_stopped"}

        pb = f"R12_restart_{key}"
        allowed, rem = _check_and_mark_cooldown(bid, pb, cooldown_sec=3600, dry_run=True)
        if not allowed:
            return {"applied": False, "skipped": f"cooldown_{rem}s"}

        if _should_hold_restart_for_positions(cwd):
            _update_pending_restart(bid, False, pb, f"{key} 해소 안전 재기동 예약", cwd)
            actions = ["보유 포지션 보호 — 청산 직후 안전 재기동 자동 예약"]
            _append_history_event(
                bid,
                pb,
                f"{key} 감지 — 청산 후 재기동 예약",
                actions,
                reason=details,
                severity=sev,
                notify_discord=True,
                extra={"eval_status": "skipped_na"},
            )
            return {"applied": True, "actions": actions}

        ok, detail = bot_restart_locked(
            bid, cwd, source=f"aegis_v9_{key}", reason=f"R12 {key} 자가복구", cooldown_sec=120
        )
        if not ok:
            return {"applied": False, "skipped": detail}
        _update_pending_restart(bid, True, pb, f"{key} 자가복구", cwd)
        actions = [f"엔진 안전 재기동 완료 ({detail})"]
        _append_history_event(
            bid,
            pb,
            f"{key} 감지 — 엔진 안전 재기동 완료",
            actions,
            reason=details,
            severity=sev,
            notify_discord=True,
            extra={"eval_status": "skipped_na"},
        )
        return {"applied": True, "actions": actions}

    return {"applied": False, "skipped": "unsupported_r12_key"}


def _extract_symbol_from_alert(alert: Dict[str, Any]) -> Optional[str]:
    text = f"{alert.get('title') or ''} {alert.get('details') or ''}"
    m = re.search(r"([A-Z0-9]+/USDT:USDT)", text)
    if m:
        return m.group(1)
    m = re.search(r"([A-Z0-9]+)-USDT-SWAP", text)
    if m:
        return f"{m.group(1)}/USDT:USDT"
    m = re.search(r"\b([A-Z0-9]{2,12})USDT\b", text)
    if m:
        return f"{m.group(1)}/USDT:USDT"
    return None


def remediate_delisting_or_funding(
    bot_id: str, cwd: str, alert: Dict[str, Any]
) -> Dict[str, Any]:
    """[Playbook R13] 상장폐지·레버리지 상한 하향·극단적 불리 펀딩비 자율 방어."""
    key = str(alert.get("key") or "")
    sev = str(alert.get("severity") or "WARN").upper()
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    if key in ("infra_delisting_risk", "infra_leverage_tier"):
        pb = f"R13_{key}"
        allowed, rem = _check_and_mark_cooldown(bot_id, pb, cooldown_sec=43200, dry_run=True)
        if not allowed:
            return {"applied": False, "skipped": f"cooldown_{rem}s"}
        cfg_path, cfg = _load_bot_config_with_backup(cwd)
        if not cfg:
            return {"applied": False, "skipped": "missing_config"}
        orig_cfg = copy.deepcopy(cfg)
        prev_values: Dict[str, Any] = {}
        actions: List[str] = []

        sym = _extract_symbol_from_alert(alert)
        act = _load_json(os.path.join(cwd, "data", "active_positions.json"), {})
        open_syms = set(act.keys()) if isinstance(act, dict) else set()
        wl = cfg.get("SYMBOL_WHITELIST")

        if key == "infra_delisting_risk":
            if sym and isinstance(wl, list) and sym in wl and sym not in open_syms and len(wl) > 10:
                prev_values["SYMBOL_WHITELIST"] = list(wl)
                cfg["SYMBOL_WHITELIST"] = [s for s in wl if s != sym]
                actions.append(f"SYMBOL_WHITELIST에서 상폐/만기 위험 종목 {sym} 자동 제외")
        else:
            if sym and isinstance(wl, list) and sym in wl and sym not in open_syms and len(wl) > MIN_WHITELIST_SIZE:
                prev_values["SYMBOL_WHITELIST"] = list(wl)
                cfg["SYMBOL_WHITELIST"] = [s for s in wl if s != sym]
                actions.append(f"레버리지 하향 종목 {sym} 화이트리스트 자동 제외")
            else:
                m = re.search(r"거래소 상한\s*([0-9.]+)x", str(alert.get("details") or ""))
                if m:
                    max_l = max(1, int(float(m.group(1))))
                    cur_l = int(float(cfg.get("LEVERAGE", 3) or 3))
                    if max_l < cur_l:
                        prev_values["LEVERAGE"] = orig_cfg.get("LEVERAGE")
                        cfg["LEVERAGE"] = max_l
                        actions.append(f"LEVERAGE: {cur_l}x→{max_l}x (거래소 상한 일치)")

        if not actions:
            return {"applied": False, "skipped": "open_pos_or_no_safe_change"}

        return _apply_and_restart(
            bot_id,
            cwd,
            pb,
            f"상장/레버리지 규격 리스크 자율 방어 ({sym or key})",
            actions,
            reason=str(alert.get("details") or key),
            cfg_path=cfg_path,
            cfg=cfg,
            severity=sev,
            force_restart_with_pos=False,
            prev_values=prev_values,
            eval_status="skipped_na",
        )

    if key == "infra_funding_drain":
        if sev != "CRITICAL":
            return {"applied": False, "skipped": "warn_monitoring"}
        allowed, rem = _check_and_mark_cooldown(bot_id, "R13_funding_defense", cooldown_sec=43200, dry_run=True)
        if not allowed:
            return {"applied": False, "skipped": f"cooldown_{rem}s"}
        cfg_path, cfg = _load_bot_config_with_backup(cwd)
        if not cfg:
            return {"applied": False, "skipped": "missing_config"}
        cur_cd = float(cfg.get("COOLDOWN_HOURS", 4.0) or 4.0)
        if cur_cd >= 6.0:
            return {"applied": False, "skipped": "already_hardened"}
        prev_values = {"COOLDOWN_HOURS": cfg.get("COOLDOWN_HOURS")}
        cfg["COOLDOWN_HOURS"] = 6.0
        actions = [f"COOLDOWN_HOURS: {cur_cd:.1f}h→6.0h (고율 불리 펀딩 종목 재진입 억제)"]
        return _apply_and_restart(
            bot_id,
            cwd,
            "R13_funding_defense",
            "극단적 불리 펀딩비 재진입 차단 쿨다운 상향",
            actions,
            reason=str(alert.get("details") or key),
            cfg_path=cfg_path,
            cfg=cfg,
            severity="WARN",
            force_restart_with_pos=False,
            prev_values=prev_values,
            eval_status="skipped_na",
        )

    return {"applied": False, "skipped": "unsupported_r13_key"}


def remediate_portfolio_or_blackswan(
    alert: Dict[str, Any], bots: List[Any]
) -> Dict[str, Any]:
    """[Playbook R14] 포트폴리오 쏠림·24h 급락·USDT 디페깅·BTC 급변동 CRITICAL 시 전 봇 자율 방어."""
    key = str(alert.get("key") or "")
    sev = str(alert.get("severity") or "WARN").upper()
    if sev != "CRITICAL":
        return {"applied": False, "skipped": "warn_monitoring"}
    if key not in ("portfolio_net_exposure", "portfolio_24h_drawdown", "blackswan_usdt_depeg", "market_regime_shock"):
        return {"applied": False, "skipped": "unsupported_r14_key"}

    pb = f"R14_{key}"
    allowed, rem = _check_and_mark_cooldown("8888", pb, cooldown_sec=21600, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    hardened: List[str] = []
    for b in bots:
        bid = str(b)
        cwd = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(cwd, ".stopped")):
            continue
        cfg_path, cfg = _load_bot_config_with_backup(cwd)
        if not cfg:
            continue
        orig_cfg = copy.deepcopy(cfg)
        b_acts: List[str] = []

        cur_mp = int(float(cfg.get("MAX_POSITIONS", 2) or 2))
        if cur_mp > 1:
            cfg["MAX_POSITIONS"] = 1
            b_acts.append(f"MP {cur_mp}→1")

        if cfg.get("USE_AUTO_COMPOUND"):
            ex_id = str(cfg.get("EXCHANGE_ID", "")).lower()
            min_cmp = 22.0 if ex_id == "binance" else 18.0
            cur_cmp = float(cfg.get("AUTO_COMPOUND_PCT", 25.0) or 25.0)
            new_cmp = max(min_cmp, round(cur_cmp * 0.80, 1))
            if new_cmp < cur_cmp - 0.5:
                cfg["AUTO_COMPOUND_PCT"] = new_cmp
                b_acts.append(f"CMP {cur_cmp:.1f}%→{new_cmp:.1f}%")

        if key == "blackswan_usdt_depeg" and cfg.get("AUTO_TRADING", True):
            cfg["AUTO_TRADING"] = False
            b_acts.append("AUTO_TRADING→False")

        if not b_acts:
            continue

        _record_pre_defense_baseline(bid, orig_cfg, ["AUTO_COMPOUND_PCT", "MAX_POSITIONS", "AUTO_TRADING"])
        _save_bot_config_with_backup(cfg_path, cfg)
        _sync_ver_md(cwd, f"전 계좌 블랙스완/레짐 긴급 방어 ({key})", b_acts)

        has_pos = _should_hold_restart_for_positions(cwd)
        restarted = False
        if not has_pos:
            ok, _ = bot_restart_locked(
                bid, cwd, source=f"aegis_v9_{pb}", reason=f"전 계좌 자율 방어({key})", cooldown_sec=60
            )
            restarted = bool(ok)
        _update_pending_restart(bid, restarted, pb, f"R14 긴급 방어({key})", cwd)
        state_lbl = "재기동완료" if restarted else "재기동예약"
        hardened.append(f"{bid}({', '.join(b_acts)} / {state_lbl})")

    if not hardened:
        return {"applied": False, "skipped": "fleet_already_hardened"}

    _append_history_event(
        "8888",
        pb,
        f"전 계좌 시스템 방어 자율 발동 ({key})",
        hardened,
        reason=str(alert.get("details") or alert.get("title") or key),
        severity="CRITICAL",
        notify_discord=True,
        extra={"eval_status": "skipped_na"},
    )
    return {"applied": True, "actions": hardened}


def remediate_tca_or_otr(
    bot_id: str, cwd: str, alert: Dict[str, Any]
) -> Dict[str, Any]:
    """[Playbook R15] TCA 체결 품질 저하(R3 연계) 및 OTR 주문 폭주 즉시 제어."""
    key = str(alert.get("key") or "")
    sev = str(alert.get("severity") or "WARN").upper()
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    if key in ("tca_fee_slippage_spike", "tca_maker_fill_low", "tca_adverse_selection"):
        if key == "tca_fee_slippage_spike" or sev == "CRITICAL":
            return remediate_fee_or_alpha_decay(bot_id, cwd, f"R15_{key}", closed_all=25)
        return {"applied": False, "skipped": "warn_monitoring"}

    if key == "otr_runaway_algo":
        if sev != "CRITICAL":
            return {"applied": False, "skipped": "warn_monitoring"}
        allowed, rem = _check_and_mark_cooldown(bot_id, "R15_otr_throttle", cooldown_sec=3600, dry_run=True)
        if not allowed:
            return {"applied": False, "skipped": f"cooldown_{rem}s"}
        cfg_path, cfg = _load_bot_config_with_backup(cwd)
        if not cfg:
            return {"applied": False, "skipped": "missing_config"}
        prev_values: Dict[str, Any] = {}
        actions: List[str] = []
        cur_cd = float(cfg.get("COOLDOWN_HOURS", 4.0) or 4.0)
        if cur_cd < 6.0:
            prev_values["COOLDOWN_HOURS"] = cfg.get("COOLDOWN_HOURS")
            cfg["COOLDOWN_HOURS"] = 6.0
            actions.append(f"COOLDOWN_HOURS: {cur_cd:.1f}h→6.0h (OTR 폭주 차단)")
        else:
            actions.append("OTR 주문 루프 해소를 위한 즉시 안전 재기동")
        return _apply_and_restart(
            bot_id,
            cwd,
            "R15_otr_throttle",
            "OTR 주문 폭주 감지 — 즉시 억제 및 재기동",
            actions,
            reason=str(alert.get("details") or key),
            cfg_path=cfg_path,
            cfg=cfg,
            severity="CRITICAL",
            force_restart_with_pos=True,
            prev_values=prev_values or None,
            eval_status="skipped_na",
        )

    return {"applied": False, "skipped": "unsupported_r15_key"}


def dispatch_aegis_alert_remediations(
    alerts: List[Dict[str, Any]],
    bots: List[Any],
    portfolio_summary: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    [Universal Alert Dispatcher] M16~M34 전 선제 경보 항목을 해당 자율 조치 플레이북(R3/R12~R15)으로 라우팅하고,
    수동 확인 권고 문구 대신 실제 자율 조치 결과 또는 외부 개입 필요 여부를 기록한다.
    """
    allowed_bots = {str(b) for b in bots}
    per_bot_alpha = ((portfolio_summary or {}).get("m22_alpha") or {}).get("per_bot_alpha") or {}
    kept_alerts: List[Dict[str, Any]] = []

    for a in (alerts or []):
        if not isinstance(a, dict):
            continue
        bid = str(a.get("bot_id") or "8888")
        key = str(a.get("key") or "")
        cwd = os.path.join(BASE_PROJECT, bid)
        res: Optional[Dict[str, Any]] = None

        if key == "alpha_decay_early" and bid in allowed_bots:
            sample_n = int((per_bot_alpha.get(bid) or {}).get("sample_n") or 30)
            res = remediate_fee_or_alpha_decay(
                bid, cwd, f"M22조기알파감쇠({a.get('severity', 'WARN')})", closed_all=max(sample_n, 25)
            )
        elif key in (
            "security_env_writable",
            "security_env_readable",
            "security_json_corrupted",
            "infra_orphan_helpers",
            "infra_disk_full",
            "infra_memory_leak",
            "infra_fd_leak",
            "feed_stale_scan",
            "feed_frozen_prices",
        ):
            res = remediate_infra_or_security_alert(a, bots)
            if res.get("suppress_alert"):
                continue
        elif key in ("infra_delisting_risk", "infra_leverage_tier", "infra_funding_drain") and bid in allowed_bots:
            res = remediate_delisting_or_funding(bid, cwd, a)
        elif key in ("portfolio_net_exposure", "portfolio_24h_drawdown", "blackswan_usdt_depeg", "market_regime_shock"):
            res = remediate_portfolio_or_blackswan(a, bots)
        elif key in ("tca_fee_slippage_spike", "tca_maker_fill_low", "tca_adverse_selection", "otr_runaway_algo") and bid in allowed_bots:
            res = remediate_tca_or_otr(bid, cwd, a)
        elif key.startswith("portfolio_crowding_"):
            a["recommendation"] = "Level 2+ 포트폴리오 집중 감시 중 (Peak-MDD/R14 방어 자동 연동)"
            kept_alerts.append(a)
            continue
        elif any(key.startswith(pref) for pref in EXTERNAL_ONLY_ALERT_PREFIXES):
            rec_old = str(a.get("recommendation") or "")
            if "[외부 계정/OS 개입 필요]" not in rec_old:
                a["recommendation"] = f"[외부 계정/OS 개입 필요] {rec_old}".strip()
            kept_alerts.append(a)
            continue

        if res is not None:
            if res.get("applied"):
                a["recommendation"] = f"Level 2+ 자율 조치 완료: {', '.join(res.get('actions') or [])}"
            else:
                a["recommendation"] = f"Level 2+ 자율 감시 유지 ({res.get('skipped') or '정상 대기'})"
        kept_alerts.append(a)

    return kept_alerts


def remediate_execution_parity_defects(
    bot_id: str, cwd: str, detail_msg: str
) -> Dict[str, Any]:
    """[Playbook R17] 실행 정합성 결함(DYNAMIC_SL_CAP_PCT < MAX_SL_PCT 등) 자율 보정."""
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    allowed, rem = _check_and_mark_cooldown(bot_id, "R17_exec_parity", cooldown_sec=21600, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []

    cap_val = cfg.get("DYNAMIC_SL_CAP_PCT")
    max_sl = cfg.get("MAX_SL_PCT")
    sl_str = str(((cfg.get("DASHBOARD_META") or {}).get("sl_str")) or "")
    if cap_val is not None and max_sl is not None:
        f_cap = float(cap_val)
        f_max = float(max_sl)
        if f_cap < f_max - 1e-4 and ("캡1.5%" not in sl_str) and (f"{f_max*100:.1f}%" in sl_str):
            prev_values["DYNAMIC_SL_CAP_PCT"] = orig_cfg.get("DYNAMIC_SL_CAP_PCT")
            cfg["DYNAMIC_SL_CAP_PCT"] = f_max
            actions.append(f"DYNAMIC_SL_CAP_PCT: {f_cap:.3f}→{f_max:.3f} (설계 SL 상한 일치)")

    if not actions:
        return {"applied": False, "skipped": "requires_code_fix_or_already_synced"}

    return _apply_and_restart(
        bot_id,
        cwd,
        "R17_exec_parity",
        "실행 정합성(SL_CAP) 불일치 자율 보정",
        actions,
        reason=detail_msg,
        cfg_path=cfg_path,
        cfg=cfg,
        severity="WARN",
        force_restart_with_pos=False,
        prev_values=prev_values,
        eval_status="skipped_na",
    )


def sync_peer_be_guard(bots: List[Any], baselines_doc: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """동일 전략군(strategy_id + timeframe) 내 검증 상향된 BE_GUARD_TRIGGER_PCT를 후행 피어 봇에 동기화한다."""
    synced: List[Dict[str, Any]] = []
    if not baselines_doc:
        baselines_doc = _load_json(os.path.join(BASE_8888, "strategy_baselines.json"), {}) or {}
    bl_bots = baselines_doc.get("bots") or {}

    # Group non-stopped bots by (strategy_id, timeframe)
    groups: Dict[Tuple[str, str], List[Tuple[str, str, Dict[str, Any]]]] = {}
    for b in bots:
        bid = str(b)
        cwd = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(cwd, ".stopped")):
            continue
        cfg = _load_json(os.path.join(cwd, "config.json"), {}) or {}
        if not isinstance(cfg, dict) or not cfg:
            continue
        sid = str((bl_bots.get(bid) or {}).get("strategy_id") or "")
        tf = str(cfg.get("TIMEFRAME") or "").strip()
        if not sid or not tf:
            continue
        groups.setdefault((sid, tf), []).append((bid, cwd, cfg))

    for (sid, tf), members in groups.items():
        if len(members) < 2:
            continue
        be_vals = [float(c.get("BE_GUARD_TRIGGER_PCT", 0.0) or 0.0) for _, _, c in members if "BE_GUARD_TRIGGER_PCT" in c]
        if len(be_vals) < 2:
            continue
        max_be = max(be_vals)
        min_be = min(be_vals)
        if max_be - min_be < 0.002:
            continue

        for bid, cwd, cfg in members:
            if "BE_GUARD_TRIGGER_PCT" not in cfg:
                continue
            cur_be = float(cfg.get("BE_GUARD_TRIGGER_PCT", 0.0) or 0.0)
            ts_act = float(cfg.get("TRAILING_ACTIVATE_PCT", 0.03) or 0.03)
            safe_target = min(max_be, round(ts_act - 0.002, 3))
            if cur_be >= safe_target - 1e-4:
                continue
            allowed, _ = _check_and_mark_cooldown(bid, "R17_peer_be_sync", cooldown_sec=86400, dry_run=True)
            if not allowed:
                continue
            cfg_path, latest_cfg = _load_bot_config_with_backup(cwd)
            if not latest_cfg:
                continue
            prev_vals = {"BE_GUARD_TRIGGER_PCT": latest_cfg.get("BE_GUARD_TRIGGER_PCT")}
            if "DASHBOARD_META" in latest_cfg:
                prev_vals["DASHBOARD_META"] = copy.deepcopy(latest_cfg["DASHBOARD_META"])
            latest_cfg["BE_GUARD_TRIGGER_PCT"] = safe_target
            _sync_meta_be(latest_cfg, safe_target)
            res = _apply_and_restart(
                bid,
                cwd,
                "R17_peer_be_sync",
                f"동일 전략군({sid}) BE가드 자율 동기화",
                [f"BE_GUARD_TRIGGER_PCT: +{cur_be*100:.1f}%→+{safe_target*100:.1f}% (피어 기준 일치)"],
                reason=f"동일 전략군({sid}/{tf}) 피어 봇 BE가드 기준(+{safe_target*100:.1f}%) 정렬",
                cfg_path=cfg_path,
                cfg=latest_cfg,
                severity="INFO",
                force_restart_with_pos=False,
                prev_values=prev_vals,
                eval_status="skipped_na",
            )
            if res.get("applied"):
                synced.append({"bot_id": bid, "strategy_id": sid, "be": safe_target})

    return synced


# ── [Aegis V10 Playbooks R18 ~ R23: 9-Module Profitability Suite Remediations] ─────
def remediate_mae_mfe_exit_efficiency(
    bot_id: str, cwd: str, m36_info: Dict[str, Any], detail_msg: str = ""
) -> Dict[str, Any]:
    """[Playbook R18] M36 MAE/MFE 청산효율 저하 시 본절가드/트레일링 발동선 미세 상향 (R8 추적)."""
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    pb = "R18_mae_mfe_tune"
    allowed, rem = _check_and_mark_cooldown(bot_id, pb, cooldown_sec=86400, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []
    block_sigs: List[str] = []

    premature = _safe_float(m36_info.get("premature_be_ratio"), 0.0)
    avg_eff = _safe_float(m36_info.get("avg_exit_efficiency"), 0.5)

    if cfg.get("USE_BE_GUARD") and "BE_GUARD_TRIGGER_PCT" in cfg and not _is_action_blocked(bot_id, f"{pb}:BE_GUARD_TRIGGER_PCT"):
        cur_be = _safe_float(cfg.get("BE_GUARD_TRIGGER_PCT"), 0.016)
        if cur_be < 0.025 and (premature >= 0.45 or avg_eff < 0.35):
            new_be = min(0.025, round(cur_be + 0.002, 4))
            if new_be > cur_be + 1e-4:
                prev_values["BE_GUARD_TRIGGER_PCT"] = orig_cfg.get("BE_GUARD_TRIGGER_PCT")
                if "DASHBOARD_META" in orig_cfg:
                    prev_values["DASHBOARD_META"] = copy.deepcopy(orig_cfg["DASHBOARD_META"])
                cfg["BE_GUARD_TRIGGER_PCT"] = new_be
                _sync_meta_be(cfg, new_be)
                block_sigs.append("BE_GUARD_TRIGGER_PCT")
                actions.append(f"BE_GUARD_TRIGGER_PCT: +{cur_be*100:.1f}%→+{new_be*100:.1f}% (조기본절 완화)")

    if not actions and cfg.get("USE_TRAILING_STOP") and "TRAILING_ACTIVATE_PCT" in cfg and not _is_action_blocked(bot_id, f"{pb}:TRAILING_ACTIVATE_PCT"):
        cur_ts = _safe_float(cfg.get("TRAILING_ACTIVATE_PCT"), 0.018)
        if cur_ts < 0.040 and avg_eff < 0.35:
            new_ts = min(0.040, round(cur_ts + 0.003, 4))
            if new_ts > cur_ts + 1e-4:
                prev_values["TRAILING_ACTIVATE_PCT"] = orig_cfg.get("TRAILING_ACTIVATE_PCT")
                cfg["TRAILING_ACTIVATE_PCT"] = new_ts
                block_sigs.append("TRAILING_ACTIVATE_PCT")
                actions.append(f"TRAILING_ACTIVATE_PCT: +{cur_ts*100:.1f}%→+{new_ts*100:.1f}% (수익 뻗음 여유 확대)")

    if not actions:
        return {"applied": False, "skipped": "already_tuned_or_blocked"}

    base_metrics = _compute_window_metrics(cwd, since_ts=time.time() - 7 * 86400)
    return _apply_and_restart(
        bot_id,
        cwd,
        pb,
        "M36 청산효율 기반 BE/TS 발동선 자율 최적화",
        actions,
        reason=detail_msg or "M36 MAE/MFE 청산효율 저하",
        cfg_path=cfg_path,
        cfg=cfg,
        severity="WARN",
        force_restart_with_pos=False,
        prev_values=prev_values,
        baseline_metrics=base_metrics,
        eval_status="pending",
        block_sigs=block_sigs,
    )


def remediate_illiquid_spread_symbols(
    bot_id: str, cwd: str, bad_symbols: List[Dict[str, Any]], detail_msg: str = ""
) -> Dict[str, Any]:
    """[Playbook R19] M37 고스프레드·저유동성 비보유 종목 화이트리스트 자율 제외."""
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    pb = "R19_spread_prune"
    allowed, rem = _check_and_mark_cooldown(bot_id, pb, cooldown_sec=86400, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    wl = cfg.get("SYMBOL_WHITELIST")
    if not isinstance(wl, list) or len(wl) <= MIN_WHITELIST_SIZE:
        return {"applied": False, "skipped": "whitelist_min_floor"}

    act = _load_json(os.path.join(cwd, "data", "active_positions.json"), {})
    open_syms = set(act.keys()) if isinstance(act, dict) else set()

    prune_candidates = [
        x["symbol"] for x in (bad_symbols or [])
        if isinstance(x, dict) and x.get("symbol") in wl and x.get("symbol") not in open_syms
    ]
    max_rm = max(0, len(wl) - MIN_WHITELIST_SIZE)
    to_remove = prune_candidates[: min(2, max_rm)]
    if not to_remove:
        return {"applied": False, "skipped": "no_safe_unheld_illiquid_symbol"}

    prev_values = {"SYMBOL_WHITELIST": list(wl)}
    cfg["SYMBOL_WHITELIST"] = [s for s in wl if s not in set(to_remove)]
    actions = [f"고스프레드/저유동성 종목 제외: {', '.join(to_remove)} ({len(wl)}→{len(cfg['SYMBOL_WHITELIST'])}개)"]

    return _apply_and_restart(
        bot_id,
        cwd,
        pb,
        "M37 고스프레드·저유동성 종목 자율 제외",
        actions,
        reason=detail_msg or "M37 Spread/ATR 과다",
        cfg_path=cfg_path,
        cfg=cfg,
        severity="WARN",
        force_restart_with_pos=False,
        prev_values=prev_values,
        eval_status="skipped_na",
    )


def remediate_cusum_sprt_edge_decay(
    bot_id: str, cwd: str, m38_info: Dict[str, Any], sev: str = "WARN", detail_msg: str = ""
) -> Dict[str, Any]:
    """[Playbook R20] M38 CUSUM/SPRT 조기 알파 감쇠 감지 시 비중 축소·동적레짐 방어."""
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    pb = "R20_cusum_decay"
    allowed, rem = _check_and_mark_cooldown(bot_id, pb, cooldown_sec=86400, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []

    if not cfg.get("USE_DYNAMIC_REGIME", False):
        prev_values["USE_DYNAMIC_REGIME"] = orig_cfg.get("USE_DYNAMIC_REGIME", False)
        cfg["USE_DYNAMIC_REGIME"] = True
        actions.append("USE_DYNAMIC_REGIME: False→True (연패 시드 방어 활성)")

    if cfg.get("USE_AUTO_COMPOUND"):
        ex_id = str(cfg.get("EXCHANGE_ID", "")).lower()
        min_cmp = 22.0 if ex_id == "binance" else 18.0
        cur_cmp = _safe_float(cfg.get("AUTO_COMPOUND_PCT"), 25.0)
        new_cmp = max(min_cmp, round(cur_cmp * 0.80, 1))
        if new_cmp < cur_cmp - 0.5:
            prev_values["AUTO_COMPOUND_PCT"] = orig_cfg.get("AUTO_COMPOUND_PCT")
            cfg["AUTO_COMPOUND_PCT"] = new_cmp
            actions.append(f"AUTO_COMPOUND_PCT: {cur_cmp:.1f}%→{new_cmp:.1f}% (CUSUM/SPRT 감쇠 방어)")
    elif "RISK_PER_TRADE_PCT" in cfg:
        cur_r = _safe_float(cfg.get("RISK_PER_TRADE_PCT"), 0.01)
        new_r = max(0.006, round(cur_r * 0.75, 4))
        if new_r < cur_r - 0.0005:
            prev_values["RISK_PER_TRADE_PCT"] = orig_cfg.get("RISK_PER_TRADE_PCT")
            cfg["RISK_PER_TRADE_PCT"] = new_r
            actions.append(f"RISK_PER_TRADE_PCT: {cur_r*100:.2f}%→{new_r*100:.2f}% (M4 알파감쇠 선제 감축)")

    if sev == "CRITICAL" and int(_safe_float(cfg.get("MAX_POSITIONS"), 2)) > 1:
        cur_mp = int(_safe_float(cfg.get("MAX_POSITIONS"), 2))
        prev_values["MAX_POSITIONS"] = orig_cfg.get("MAX_POSITIONS")
        cfg["MAX_POSITIONS"] = 1
        actions.append(f"MAX_POSITIONS: {cur_mp}→1 (CRITICAL 감쇠 동시노출 축소)")

    if not actions:
        return {"applied": False, "skipped": "already_at_defensive_floor"}

    def_keys = [k for k in ("AUTO_COMPOUND_PCT", "RISK_PER_TRADE_PCT", "MAX_POSITIONS") if k in prev_values]
    return _apply_and_restart(
        bot_id,
        cwd,
        pb,
        f"M38 CUSUM/SPRT 알파 감쇠 선제 방어 ({sev})",
        actions,
        reason=detail_msg or f"CUSUM={m38_info.get('cusum')} SPRT={m38_info.get('sprt')}",
        cfg_path=cfg_path,
        cfg=cfg,
        severity=sev,
        force_restart_with_pos=False,
        prev_values=prev_values,
        eval_status="skipped_na",
        record_defense_baseline_keys=def_keys or None,
    )


def remediate_funding_seasonality_or_skew(
    bot_id: str, cwd: str, alert: Dict[str, Any], suite_report: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """[Playbook R21] M39 펀딩 유출 · M40 취약세션 · M43 방향 비대칭 자율 보정."""
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    key = str(alert.get("key") or "")
    pb = "R21_dir_skew" if key == "prof_dir_expectancy_skew" else f"R21_{key}"
    allowed, rem = _check_and_mark_cooldown(bot_id, pb, cooldown_sec=86400, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []
    block_sigs: List[str] = []
    eval_st = "skipped_na"

    if key in ("prof_funding_carry_drain", "prof_session_seasonality"):
        cur_cd = _safe_float(cfg.get("COOLDOWN_HOURS"), 4.0)
        target_cd = 6.0 if key == "prof_funding_carry_drain" else min(8.0, cur_cd + 2.0)
        if cur_cd < target_cd - 0.1:
            prev_values["COOLDOWN_HOURS"] = orig_cfg.get("COOLDOWN_HOURS")
            cfg["COOLDOWN_HOURS"] = target_cd
            actions.append(f"COOLDOWN_HOURS: {cur_cd:.1f}h→{target_cd:.1f}h ({key} 재진입 억제)")
    elif key == "prof_dir_expectancy_skew":
        m43_bot = (((suite_report or {}).get("m43_dir_skew") or {}).get("per_bot") or {}).get(str(bot_id)) or {}
        weak_side = m43_bot.get("weak_side")
        is_trend_bot = str(bot_id) in ("8401", "8402", "8405", "8407", "8409", "8410")
        if weak_side == "short" and (not is_trend_bot) and not _is_action_blocked(bot_id, f"{pb}:ASYMMETRIC_SHORT_TP"):
            cur_asym = _safe_float(cfg.get("ASYMMETRIC_SHORT_TP"), 1.0)
            if cur_asym > 0.85:
                prev_values["ASYMMETRIC_SHORT_TP"] = orig_cfg.get("ASYMMETRIC_SHORT_TP", 1.0)
                cfg["ASYMMETRIC_SHORT_TP"] = 0.85
                block_sigs.append("ASYMMETRIC_SHORT_TP")
                actions.append(f"ASYMMETRIC_SHORT_TP: {cur_asym:.2f}→0.85 (비추세 봇 숏 손익비 보수화)")
                eval_st = "pending"
        if not cfg.get("USE_DYNAMIC_REGIME", False):
            prev_values["USE_DYNAMIC_REGIME"] = orig_cfg.get("USE_DYNAMIC_REGIME", False)
            cfg["USE_DYNAMIC_REGIME"] = True
            actions.append("USE_DYNAMIC_REGIME: False→True (편향 연패 방어)")

    if not actions:
        return {"applied": False, "skipped": "already_hardened_or_no_safe_change"}

    base_metrics = _compute_window_metrics(cwd, since_ts=time.time() - 7 * 86400) if eval_st == "pending" else None
    return _apply_and_restart(
        bot_id,
        cwd,
        pb,
        f"펀딩/세션/방향 비대칭 자율 보정 ({key})",
        actions,
        reason=str(alert.get("details") or key),
        cfg_path=cfg_path,
        cfg=cfg,
        severity="WARN",
        force_restart_with_pos=False,
        prev_values=prev_values,
        baseline_metrics=base_metrics,
        eval_status=eval_st,
        block_sigs=block_sigs or None,
    )


def remediate_corr_spike_and_hrp_budget(
    alert: Dict[str, Any], bots: List[Any], m42_info: Dict[str, Any]
) -> Dict[str, Any]:
    """[Playbook R22] M42 플릿 상관관계 CRITICAL 급등 시 전 봇 리스크 예산 동시 압축."""
    sev = str(alert.get("severity") or "WARN").upper()
    if sev != "CRITICAL":
        return {"applied": False, "skipped": "warn_hrp_monitoring_only"}

    pb = "R22_corr_spike"
    allowed, rem = _check_and_mark_cooldown("8888", pb, cooldown_sec=86400, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    hardened: List[str] = []
    for b in bots:
        bid = str(b)
        cwd = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(cwd, ".stopped")):
            continue
        cfg_path, cfg = _load_bot_config_with_backup(cwd)
        if not cfg:
            continue
        orig_cfg = copy.deepcopy(cfg)
        b_acts: List[str] = []

        cur_mp = int(_safe_float(cfg.get("MAX_POSITIONS"), 2))
        if cur_mp > 1:
            cfg["MAX_POSITIONS"] = 1
            b_acts.append(f"MP {cur_mp}→1")

        if cfg.get("USE_AUTO_COMPOUND"):
            ex_id = str(cfg.get("EXCHANGE_ID", "")).lower()
            min_cmp = 22.0 if ex_id == "binance" else 18.0
            cur_cmp = _safe_float(cfg.get("AUTO_COMPOUND_PCT"), 25.0)
            new_cmp = max(min_cmp, round(cur_cmp * 0.80, 1))
            if new_cmp < cur_cmp - 0.5:
                cfg["AUTO_COMPOUND_PCT"] = new_cmp
                b_acts.append(f"CMP {cur_cmp:.1f}%→{new_cmp:.1f}%")
        elif "RISK_PER_TRADE_PCT" in cfg:
            cur_r = _safe_float(cfg.get("RISK_PER_TRADE_PCT"), 0.01)
            new_r = max(0.006, round(cur_r * 0.80, 4))
            if new_r < cur_r - 0.0005:
                cfg["RISK_PER_TRADE_PCT"] = new_r
                b_acts.append(f"M4 {cur_r*100:.2f}%→{new_r*100:.2f}%")

        if not b_acts:
            continue

        _record_pre_defense_baseline(bid, orig_cfg, ["AUTO_COMPOUND_PCT", "RISK_PER_TRADE_PCT", "MAX_POSITIONS"])
        _save_bot_config_with_backup(cfg_path, cfg)
        _sync_ver_md(cwd, f"M42 상관급등(ρ={m42_info.get('avg_corr')}) 리스크 압축", b_acts)
        has_pos = _should_hold_restart_for_positions(cwd)
        restarted = False
        if not has_pos:
            ok, _ = bot_restart_locked(bid, cwd, source=f"aegis_v10_{pb}", reason="M42 상관급등 방어", cooldown_sec=60)
            restarted = bool(ok)
        _update_pending_restart(bid, restarted, pb, "R22 상관급등 리스크 압축", cwd)
        hardened.append(f"{bid}({', '.join(b_acts)})")

    if not hardened:
        return {"applied": False, "skipped": "fleet_already_compressed"}

    _append_history_event(
        "8888",
        pb,
        f"M42 플릿 상관급등(ρ={m42_info.get('avg_corr')}) 리스크 동시 압축",
        hardened,
        reason=str(alert.get("details") or pb),
        severity="CRITICAL",
        notify_discord=True,
        extra={"eval_status": "skipped_na"},
    )
    return {"applied": True, "actions": hardened}


def remediate_oi_crowding_or_shadow_filter(
    bot_id: str, cwd: str, alert: Dict[str, Any]
) -> Dict[str, Any]:
    """[Playbook R23] M41 OI/베이시스 과열 쿨다운 보수화 및 M44 과도 쿨다운 필터 완화."""
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    key = str(alert.get("key") or "")
    pb = "R23_shadow_relax" if key == "prof_shadow_opp_cost" else "R23_oi_crowding"
    allowed, rem = _check_and_mark_cooldown(bot_id, pb, cooldown_sec=86400, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg:
        return {"applied": False, "skipped": "missing_config"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []
    block_sigs: List[str] = []
    eval_st = "skipped_na"

    if key == "prof_oi_basis_crowding":
        cur_cd = _safe_float(cfg.get("COOLDOWN_HOURS"), 4.0)
        if cur_cd < 6.0:
            prev_values["COOLDOWN_HOURS"] = orig_cfg.get("COOLDOWN_HOURS")
            cfg["COOLDOWN_HOURS"] = 6.0
            actions.append(f"COOLDOWN_HOURS: {cur_cd:.1f}h→6.0h (OI/베이시스 과열 추격 억제)")
    elif key == "prof_shadow_opp_cost" and not _is_action_blocked(bot_id, f"{pb}:COOLDOWN_HOURS"):
        meta = alert.get("meta") if isinstance(alert.get("meta"), dict) else {}
        if not meta.get("opp_hit") or meta.get("dominant_filter") != "쿨다운":
            return {"applied": False, "skipped": "drift_or_non_cooldown_monitor_only"}
        # Mutual exclusion: do not relax cooldown if a defensive cooldown tightening ran within 24h
        hist_doc = _ensure_history_shape(_load_json(HISTORY_FILE, {}))
        now_ts = time.time()
        for def_pb in ("R2_mdd_warn", "R2_mdd_kill", "R3_alpha_tune", "R11_loss_streak_warn", "R11_loss_streak_kill", "R21_prof_session_seasonality", "R21_prof_funding_carry_drain"):
            last_def = _safe_float((hist_doc.get("cooldowns") or {}).get(f"{bot_id}:{def_pb}"), 0.0)
            if (now_ts - last_def) < 86400:
                return {"applied": False, "skipped": f"cooldown_hardened_recently_{def_pb}"}
        cur_cd = _safe_float(cfg.get("COOLDOWN_HOURS"), 4.0)
        if cur_cd > 4.0:
            new_cd = max(4.0, round(cur_cd - 2.0, 1))
            prev_values["COOLDOWN_HOURS"] = orig_cfg.get("COOLDOWN_HOURS")
            cfg["COOLDOWN_HOURS"] = new_cd
            block_sigs.append("COOLDOWN_HOURS")
            actions.append(f"COOLDOWN_HOURS: {cur_cd:.1f}h→{new_cd:.1f}h (M44 탈락 알파 회수)")
            eval_st = "pending"

    if not actions:
        return {"applied": False, "skipped": "no_safe_adjustment"}

    base_metrics = _compute_window_metrics(cwd, since_ts=time.time() - 7 * 86400) if eval_st == "pending" else None
    return _apply_and_restart(
        bot_id,
        cwd,
        pb,
        f"OI 과열/섀도우 알파 기회비용 보정 ({key})",
        actions,
        reason=str(alert.get("details") or key),
        cfg_path=cfg_path,
        cfg=cfg,
        severity="WARN",
        force_restart_with_pos=False,
        prev_values=prev_values,
        baseline_metrics=base_metrics,
        eval_status=eval_st,
        block_sigs=block_sigs or None,
    )


def dispatch_alpha_profitability_remediations(
    alerts: List[Dict[str, Any]],
    bots: List[Any],
    suite_report: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """[Aegis V10 Alpha Dispatcher] M36~M44(`prof_*`) 경보를 R18~R23 플레이북에 자율 라우팅."""
    allowed_bots = {str(b) for b in bots}
    rep = suite_report or {}
    kept: List[Dict[str, Any]] = []
    mutated_bots = set()

    for a in (alerts or []):
        if not isinstance(a, dict):
            continue
        bid = str(a.get("bot_id") or "8888")
        key = str(a.get("key") or "")
        sev = str(a.get("severity") or "WARN").upper()
        cwd = os.path.join(BASE_PROJECT, bid)
        res: Optional[Dict[str, Any]] = None

        if bid in mutated_bots and bid in allowed_bots:
            a["recommendation"] = "Level 2+ 금회 사이클 이미 1건 자율 조치 완료 (핑퐁 방지)"
            kept.append(a)
            continue

        if key == "prof_mae_mfe_exit_eff" and bid in allowed_bots:
            m36_info = ((rep.get("m36_mae_mfe") or {}).get("per_bot") or {}).get(bid) or {}
            res = remediate_mae_mfe_exit_efficiency(bid, cwd, m36_info, detail_msg=str(a.get("details") or ""))
        elif key == "prof_slippage_spread_atr" and bid in allowed_bots:
            bad_syms = (((rep.get("m37_slippage_spread") or {}).get("per_bot") or {}).get(bid) or {}).get("illiquid_symbols") or []
            res = remediate_illiquid_spread_symbols(bid, cwd, bad_syms, detail_msg=str(a.get("details") or ""))
        elif key == "prof_cusum_sprt_decay" and bid in allowed_bots:
            m38_info = ((rep.get("m38_cusum_sprt") or {}).get("per_bot") or {}).get(bid) or {}
            res = remediate_cusum_sprt_edge_decay(bid, cwd, m38_info, sev=sev, detail_msg=str(a.get("details") or ""))
        elif key in ("prof_funding_carry_drain", "prof_session_seasonality", "prof_dir_expectancy_skew") and bid in allowed_bots:
            res = remediate_funding_seasonality_or_skew(bid, cwd, a, suite_report=rep)
        elif key == "prof_corr_spike_hrp":
            res = remediate_corr_spike_and_hrp_budget(a, bots, rep.get("m42_corr_hrp") or {})
        elif key in ("prof_oi_basis_crowding", "prof_shadow_opp_cost") and bid in allowed_bots:
            res = remediate_oi_crowding_or_shadow_filter(bid, cwd, a)

        if res is not None:
            if res.get("applied"):
                mutated_bots.add(bid)
                a["recommendation"] = f"Level 2+ 자율 조치 완료: {', '.join(res.get('actions') or [])}"
            else:
                a["recommendation"] = f"Level 2+ 자율 감시 유지 ({res.get('skipped') or '정상 대기'})"
        kept.append(a)

    return kept


# ── [Aegis V10.5 Playbooks R24 ~ R29: Historical Incident Self-Healing] ──────────────
def remediate_bot_ui_only(bot_id: str, cwd: str, alert: Dict[str, Any]) -> Dict[str, Any]:
    """[Playbook R24] Restart ONLY the bot's Streamlit UI process without disturbing bot.py."""
    if os.path.exists(os.path.join(cwd, ".stopped")) or not str(bot_id).isdigit():
        return {"applied": False, "skipped": "bot_stopped_or_invalid"}

    pb = "R24_ui_only_restart"
    allowed, rem = _check_and_mark_cooldown(bot_id, pb, cooldown_sec=900, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    py_bin = os.path.join(cwd, "venv", "bin", "python3")
    if not os.path.exists(py_bin):
        py_bin = "/usr/bin/python3"
    app_py = os.path.join(cwd, "app.py")
    if not os.path.exists(app_py):
        return {"applied": False, "skipped": "app_py_missing"}

    try:
        lsof_res = subprocess.run(["lsof", f"-tiTCP:{bot_id}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=3)
        for p in lsof_res.stdout.splitlines():
            p = p.strip()
            if p.isdigit():
                try:
                    os.kill(int(p), signal.SIGTERM)
                except Exception:
                    pass
        time.sleep(1.0)
        ui_log = os.path.join(cwd, "streamlit_server.log")
        with open(ui_log, "a", encoding="utf-8") as lf:
            proc = subprocess.Popen(
                [py_bin, "-m", "streamlit", "run", "app.py", "--server.port", str(bot_id), "--server.headless", "true"],
                cwd=cwd,
                stdout=lf,
                stderr=lf,
                start_new_session=True,
            )
        _check_and_mark_cooldown(bot_id, pb, cooldown_sec=900, dry_run=False)
        acts = [f"Streamlit UI 단독 재기동 완료 (PID {proc.pid}, 포트 {bot_id}, bot.py 무중단)"]
        _append_history_event(str(bot_id), pb, "M45 개별 봇 UI 단독 복구", acts, str(alert.get("details") or pb), severity="WARN", notify_discord=True, extra={"eval_status": "skipped_na"})
        return {"applied": True, "actions": acts}
    except Exception as exc:
        return {"applied": False, "skipped": f"ui_restart_err:{exc}"}


def remediate_cross_exchange_symbols(bot_id: str, cwd: str, alert: Dict[str, Any]) -> Dict[str, Any]:
    """[Playbook R25] Prune cross-exchange/unlisted symbols from SYMBOL_WHITELIST safely."""
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    pb = "R25_cross_exchange_prune"
    allowed, rem = _check_and_mark_cooldown(bot_id, pb, cooldown_sec=43200, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    bad_syms = ((alert.get("meta") or {}).get("bad_symbols") if isinstance(alert.get("meta"), dict) else None) or []
    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg or not bad_syms:
        return {"applied": False, "skipped": "no_bad_symbols"}

    wl = cfg.get("SYMBOL_WHITELIST")
    if not isinstance(wl, list) or len(wl) <= MIN_WHITELIST_SIZE:
        return {"applied": False, "skipped": "whitelist_min_floor"}

    act = _load_json(os.path.join(cwd, "data", "active_positions.json"), {})
    open_syms = set(act.keys()) if isinstance(act, dict) else set()
    to_remove = [s for s in bad_syms if s in wl and s not in open_syms][: max(0, len(wl) - MIN_WHITELIST_SIZE)]
    if not to_remove:
        return {"applied": False, "skipped": "held_or_min_floor"}

    prev_values = {"SYMBOL_WHITELIST": list(wl)}
    cfg["SYMBOL_WHITELIST"] = [s for s in wl if s not in set(to_remove)]
    actions = [f"타거래소/미상장 종목 제외: {', '.join(to_remove)} ({len(wl)}→{len(cfg['SYMBOL_WHITELIST'])}개)"]
    return _apply_and_restart(
        bot_id, cwd, pb, "M46 타거래소 미상장 심볼 자율 정리", actions,
        reason=str(alert.get("details") or pb), cfg_path=cfg_path, cfg=cfg,
        severity="WARN", force_restart_with_pos=False, prev_values=prev_values, eval_status="skipped_na",
    )


def remediate_peak_assets_drift(alert: Dict[str, Any]) -> Dict[str, Any]:
    """[Playbook R26] Synchronize lagging peak_assets.json upward to live ATH balance."""
    pb = "R26_peak_assets_sync"
    allowed, rem = _check_and_mark_cooldown("8888", pb, cooldown_sec=3600, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    peak_lag = ((alert.get("meta") or {}).get("peak_lag") if isinstance(alert.get("meta"), dict) else None) or {}
    if not peak_lag:
        return {"applied": False, "skipped": "no_peak_lag"}

    peak_path = os.path.join(BASE_8888, "peak_assets.json")
    peak_doc = _load_json(peak_path, {}) or {}
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated_list: List[str] = []

    for bid, live_bal in peak_lag.items():
        val = _safe_float(live_bal, 0.0)
        cur = _safe_float((peak_doc.get(bid) or {}).get("peak_asset"), 0.0)
        if val > cur:
            peak_doc[bid] = {"peak_asset": round(val, 2), "peak_ts": now_str}
            updated_list.append(f"{bid}: ${cur:.2f}→${val:.2f}")

    if not updated_list:
        return {"applied": False, "skipped": "already_synced"}

    _atomic_write_json(peak_path, peak_doc)
    _check_and_mark_cooldown("8888", pb, cooldown_sec=3600, dry_run=False)
    _append_history_event("8888", pb, "M47 peak_assets 고점 자동 동기화", updated_list, str(alert.get("details") or pb), severity="INFO", notify_discord=False, extra={"eval_status": "skipped_na"})
    return {"applied": True, "actions": updated_list}


def remediate_config_hazards(bot_id: str, cwd: str, alert: Dict[str, Any]) -> Dict[str, Any]:
    """[Playbook R27] Auto-heal USE_WEBSOCKET=True, small-account EQUITY_SCALE_FACTOR<1.0, stale halt."""
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    pb = "R27_config_hazard_fix"
    allowed, rem = _check_and_mark_cooldown(bot_id, pb, cooldown_sec=43200, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    hazards = ((alert.get("meta") or {}).get("hazards") if isinstance(alert.get("meta"), dict) else None) or []
    cfg_path, cfg = _load_bot_config_with_backup(cwd)
    if not cfg or not hazards:
        return {"applied": False, "skipped": "no_hazards"}

    orig_cfg = copy.deepcopy(cfg)
    prev_values: Dict[str, Any] = {}
    actions: List[str] = []

    if "use_websocket_true" in hazards and cfg.get("USE_WEBSOCKET") is True:
        prev_values["USE_WEBSOCKET"] = True
        cfg["USE_WEBSOCKET"] = False
        actions.append("USE_WEBSOCKET: True→False (WS 크래시 부채 차단)")

    if "small_account_equity_scale_lt1" in hazards and _safe_float(cfg.get("EQUITY_SCALE_FACTOR"), 1.0) < 0.99:
        prev_values["EQUITY_SCALE_FACTOR"] = orig_cfg.get("EQUITY_SCALE_FACTOR")
        cfg["EQUITY_SCALE_FACTOR"] = 1.0
        actions.append(f"EQUITY_SCALE_FACTOR: {orig_cfg.get('EQUITY_SCALE_FACTOR')}→1.0 (소액 최소주문 충돌 방지)")

    if "stale_auto_trading_false" in hazards and cfg.get("AUTO_TRADING") is False:
        prev_values["AUTO_TRADING"] = False
        cfg["AUTO_TRADING"] = True
        actions.append("AUTO_TRADING: False→True (정상 회복 후 장기 정지 해제)")

    if not actions:
        return {"applied": False, "skipped": "already_clean"}

    return _apply_and_restart(
        bot_id, cwd, pb, "M48 위험 설정(WS/스케일/장기정지) 자율 정규화", actions,
        reason=str(alert.get("details") or pb), cfg_path=cfg_path, cfg=cfg,
        severity="WARN", force_restart_with_pos=False, prev_values=prev_values, eval_status="skipped_na",
    )


def remediate_scanner_silent_drop(bot_id: str, cwd: str, alert: Dict[str, Any]) -> Dict[str, Any]:
    """[Playbook R28] Safely restart bot experiencing silent scanner drop (<50% results or 0-vol)."""
    if os.path.exists(os.path.join(cwd, ".stopped")):
        return {"applied": False, "skipped": "bot_stopped"}

    pb = "R28_scanner_silent_heal"
    allowed, rem = _check_and_mark_cooldown(bot_id, pb, cooldown_sec=1800, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    has_pos = _should_hold_restart_for_positions(cwd)
    if has_pos:
        _update_pending_restart(str(bot_id), False, pb, "M49 스캐너 침묵 복구 재기동 예약", cwd)
        return {"applied": False, "skipped": "deferred_active_position"}

    ok, detail = bot_restart_locked(str(bot_id), cwd, source=f"aegis_v105_{pb}", reason="M49 스캐너 부분 침묵 복구", cooldown_sec=120)
    if not ok:
        return {"applied": False, "skipped": detail}
    _check_and_mark_cooldown(bot_id, pb, cooldown_sec=1800, dry_run=False)
    acts = [f"스캐너 부분 침묵 감지로 엔진 안전 재기동 완료 ({detail})"]
    _append_history_event(str(bot_id), pb, "M49 스캐너 부분 침묵 자율 복구", acts, str(alert.get("details") or pb), severity="WARN", notify_discord=True, extra={"eval_status": "skipped_na"})
    return {"applied": True, "actions": acts}


def remediate_8888_app_liveness(alert: Dict[str, Any]) -> Dict[str, Any]:
    """[Playbook R29] Safely restart 8888/app.py on HTTP down, stale code, or [DISCORD 1MIN] stall."""
    pb = "R29_8888_app_restart"
    allowed, rem = _check_and_mark_cooldown("8888", pb, cooldown_sec=900, dry_run=True)
    if not allowed:
        return {"applied": False, "skipped": f"cooldown_{rem}s"}

    app_py = os.path.join(BASE_8888, "app.py")
    app_log = os.path.join(BASE_8888, "app.log")
    app_pid = os.path.join(BASE_8888, "app.pid")
    try:
        res = subprocess.run(["pgrep", "-f", ".*8888/app.py"], capture_output=True, text=True, timeout=3)
        for p in res.stdout.splitlines():
            p = p.strip()
            if p.isdigit() and int(p) != os.getpid():
                try:
                    os.kill(int(p), signal.SIGTERM)
                except Exception:
                    pass
        time.sleep(1.5)
        with open(app_log, "a", encoding="utf-8") as lf:
            proc = subprocess.Popen(["/usr/bin/python3", app_py], cwd=BASE_8888, stdout=lf, stderr=lf, start_new_session=True)
        with open(app_pid, "w", encoding="utf-8") as pf:
            pf.write(str(proc.pid))
        _check_and_mark_cooldown("8888", pb, cooldown_sec=900, dry_run=False)
        reason_tag = ((alert.get("meta") or {}).get("reason") if isinstance(alert.get("meta"), dict) else None) or "liveness"
        acts = [f"8888/app.py 안전 재기동 완료 (PID {proc.pid}, 사유: {reason_tag})"]
        _append_history_event("8888", pb, "M50 8888 관제앱·디스코드 루프 자율 복구", acts, str(alert.get("details") or pb), severity=str(alert.get("severity") or "WARN"), notify_discord=True, extra={"eval_status": "skipped_na"})
        return {"applied": True, "actions": acts}
    except Exception as exc:
        return {"applied": False, "skipped": f"8888_restart_err:{exc}"}


def dispatch_historical_incident_remediations(
    alerts: List[Dict[str, Any]],
    bots: List[Any],
) -> List[Dict[str, Any]]:
    """[Aegis V10.5 Dispatcher] Route all `hist_*` alerts (M45~M50) to playbooks R24~R29."""
    allowed_bots = {str(b) for b in bots}
    kept: List[Dict[str, Any]] = []

    for a in (alerts or []):
        if not isinstance(a, dict):
            continue
        bid = str(a.get("bot_id") or "8888")
        key = str(a.get("key") or "")
        cwd = os.path.join(BASE_PROJECT, bid)
        res: Optional[Dict[str, Any]] = None

        if key == "hist_ui_down" and bid in allowed_bots:
            res = remediate_bot_ui_only(bid, cwd, a)
        elif key == "hist_cross_exchange_symbol" and bid in allowed_bots:
            res = remediate_cross_exchange_symbols(bid, cwd, a)
        elif key == "hist_registry_or_peak_drift" and isinstance(a.get("meta"), dict) and a["meta"].get("peak_lag"):
            res = remediate_peak_assets_drift(a)
        elif key == "hist_config_hazard" and bid in allowed_bots:
            res = remediate_config_hazards(bid, cwd, a)
        elif key == "hist_scanner_silent_drop" and bid in allowed_bots:
            res = remediate_scanner_silent_drop(bid, cwd, a)
        elif key == "hist_8888_app_stale_or_discord_halt":
            res = remediate_8888_app_liveness(a)
        elif key == "hist_duplicate_api_key":
            if str(a.get("severity") or "").upper() != "INFO":
                rec = str(a.get("recommendation") or "")
                if "[외부 계정/OS 개입 필요]" not in rec:
                    a["recommendation"] = f"[외부 계정/OS 개입 필요] {rec}".strip()
            kept.append(a)
            continue

        if res is not None:
            if res.get("applied"):
                a["recommendation"] = f"Level 2+ 자율 조치 완료: {', '.join(res.get('actions') or [])}"
            else:
                a["recommendation"] = f"Level 2+ 자율 감시 유지 ({res.get('skipped') or '정상 대기'})"
        kept.append(a)

    return kept





