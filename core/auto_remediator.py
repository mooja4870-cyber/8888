"""
core/auto_remediator.py — Aegis V8 Level 2+ 자율 적기 조치 엔진 (보스 위임 2026-11-27)

워치독 감시 활동에서 포착된 문제점에 대해 보스 사전 승인 대기 없이
안전한 클램프·쿨다운·사전 백업(.auto_bak)·공유 락 재기동(bot_restart_locked)·
디스코드 사후 보고를 결합하여 즉시 자율 적기 조치를 수행한다.

Playbooks:
  - R1: 진입 사이징/최소명목가 오류(NOTIONAL_MIN_ERROR 등) 자동 보정 (6h 쿨다운)
  - R2: Peak-MDD 주의/킬선 도달 시 자동 비중 축소·방향고정·킬선 진입정지 (12h 쿨다운)
  - R3: 수수료 적자/조기 알파 감쇠 시 단계적 파라미터·타임프레임 자율 튜닝 (24h 쿨다운)
  - R4: 생존 설정 누락(config_gap) 자동 복구 (12h 쿨다운)
  - Helper: 외부 모듈(bot_sentinel R6/R7, autonomous_auditor R5) 이력 기록 및 보고
"""
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


def _check_and_mark_cooldown(
    bot_id: str, playbook: str, cooldown_sec: int, dry_run: bool = False
) -> Tuple[bool, float]:
    """Return (allowed, remaining_sec)."""
    now = time.time()
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _load_json(HISTORY_FILE, {"last_runs": {}, "events": []})
            if not isinstance(doc, dict):
                doc = {"last_runs": {}, "events": []}
            last_runs = doc.setdefault("last_runs", {})
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
) -> None:
    now = time.time()
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(HISTORY_LOCK, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = _load_json(HISTORY_FILE, {"last_runs": {}, "events": []})
            if not isinstance(doc, dict):
                doc = {"last_runs": {}, "events": []}
            last_runs = doc.setdefault("last_runs", {})
            events = doc.setdefault("events", [])
            last_runs[f"{bot_id}:{playbook}"] = now
            events.append({
                "ts": now,
                "ts_str": now_str,
                "bot_id": str(bot_id),
                "playbook": playbook,
                "severity": severity,
                "title": title,
                "actions": list(actions),
                "reason": str(reason)[:240],
            })
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
            # Insert right under top section's ### 비고 or top if cleaner
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
) -> Dict[str, Any]:
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

    _append_history_event(
        str(bot_id), playbook, title, actions, reason, severity=severity, notify_discord=True
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

    actions: List[str] = []
    lev = max(float(cfg.get("LEVERAGE", 3.0) or 3.0), 1.0)
    ex_id = str(cfg.get("EXCHANGE_ID", "")).lower()

    if float(cfg.get("EQUITY_SCALE_FACTOR", 1.0) or 1.0) < 1.0:
        old_s = cfg.get("EQUITY_SCALE_FACTOR")
        cfg["EQUITY_SCALE_FACTOR"] = 1.0
        actions.append(f"EQUITY_SCALE_FACTOR: {old_s}→1.0")
    if ex_id == "binance" and cfg.get("USE_EQUITY_OVERLAY", False) is not False:
        cfg["USE_EQUITY_OVERLAY"] = False
        actions.append("USE_EQUITY_OVERLAY: False")

    min_safe_margin = min(3.5, round(5.5 / lev, 2))
    cur_margin = float(cfg.get("MARGIN_USDT", 1.5) or 1.5)
    if cur_margin < min_safe_margin:
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

    actions: List[str] = []
    ex_id = str(cfg.get("EXCHANGE_ID", "")).lower()
    min_cmp = 22.0 if ex_id == "binance" else 18.0

    # Reduce compound sizing safely by 20% while keeping Binance $5 floor healthy
    if cfg.get("USE_AUTO_COMPOUND"):
        cur_cmp = float(cfg.get("AUTO_COMPOUND_PCT", 25.0) or 25.0)
        new_cmp = max(min_cmp, round(cur_cmp * 0.80, 1))
        if new_cmp < cur_cmp - 0.5:
            cfg["AUTO_COMPOUND_PCT"] = new_cmp
            actions.append(f"AUTO_COMPOUND_PCT: {cur_cmp:.1f}%→{new_cmp:.1f}% (MDD 방어 감축)")

    if not cfg.get("USE_DYNAMIC_REGIME", False):
        cfg["USE_DYNAMIC_REGIME"] = True
        actions.append("USE_DYNAMIC_REGIME: False→True (연패 시드 50% 축소 활성)")

    _disable_auto_switch(cfg, actions)

    cur_max_pos = int(float(cfg.get("MAX_POSITIONS", 2) or 2))
    target_max_pos = 1 if is_kill else 2
    if cur_max_pos > target_max_pos:
        cfg["MAX_POSITIONS"] = target_max_pos
        actions.append(f"MAX_POSITIONS: {cur_max_pos}→{target_max_pos}")

    if is_kill and cfg.get("AUTO_TRADING", True):
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

    actions: List[str] = []
    cur_tf = str(cfg.get("TIMEFRAME") or "1h").strip()
    ts_act = float(cfg.get("TRAILING_ACTIVATE_PCT", 0.03) or 0.03)
    cur_be = float(cfg.get("BE_GUARD_TRIGGER_PCT", 0.0) or 0.0)
    safe_be_cap = min(0.022, round(max(cur_be, ts_act - 0.002), 3))

    # Bounded 1-step tuning ladder (1 step per 24h max)
    if cur_tf in ("5m", "15m"):
        next_tf = "15m" if cur_tf == "5m" else "1h"
        cfg["TIMEFRAME"] = next_tf
        _sync_meta_tf(cfg, cur_tf, next_tf)
        actions.append(f"TIMEFRAME: {cur_tf}→{next_tf} (수수료 잠식 완화 및 신호 품질 상향)")
    elif cfg.get("USE_AUTO_MODE_SWITCH"):
        _disable_auto_switch(cfg, actions)
    elif "BE_GUARD_TRIGGER_PCT" in cfg and cur_be < safe_be_cap - 1e-4:
        cfg["BE_GUARD_TRIGGER_PCT"] = safe_be_cap
        _sync_meta_be(cfg, safe_be_cap)
        actions.append(f"BE_GUARD_TRIGGER_PCT: +{cur_be*100:.1f}%→+{safe_be_cap*100:.1f}% (미세 본절청산 방지)")
    else:
        changed = False
        cur_cd = float(cfg.get("COOLDOWN_HOURS", 4.0) or 4.0)
        if cur_cd < 6.0:
            cfg["COOLDOWN_HOURS"] = 6.0
            actions.append(f"COOLDOWN_HOURS: {cur_cd:.1f}h→6.0h (연패 재진입 억제)")
            changed = True
        cur_mp = int(float(cfg.get("MAX_POSITIONS", 2) or 2))
        if cur_mp > 1:
            cfg["MAX_POSITIONS"] = cur_mp - 1
            actions.append(f"MAX_POSITIONS: {cur_mp}→{cur_mp - 1} (저품질 동시진입 축소)")
            changed = True
        if not changed and cfg.get("AUTO_COMPOUND_PCT"):
            ex_id = str(cfg.get("EXCHANGE_ID", "")).lower()
            min_cmp = 22.0 if ex_id == "binance" else 18.0
            cur_cmp = float(cfg.get("AUTO_COMPOUND_PCT", 25.0) or 25.0)
            if cur_cmp > min_cmp + 1.0:
                new_cmp = max(min_cmp, round(cur_cmp * 0.85, 1))
                cfg["AUTO_COMPOUND_PCT"] = new_cmp
                actions.append(f"AUTO_COMPOUND_PCT: {cur_cmp:.1f}%→{new_cmp:.1f}% (적자 방어 비중 축소)")
                changed = True
        if not changed:
            return {"applied": False, "skipped": "no_further_safe_tuning"}

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

    actions: List[str] = []
    cfg_mdd = float(cfg.get("MAX_DRAWDOWN_PCT", 0.5) or 0.5)
    rec_mdd = float(thresholds.get("recommend_max_drawdown_pct", 0.20))
    if cfg_mdd >= 0.45:
        cfg["MAX_DRAWDOWN_PCT"] = rec_mdd
        actions.append(f"MAX_DRAWDOWN_PCT: {cfg_mdd:.2f}→{rec_mdd:.2f}")

    cfg_dll = float(cfg.get("DAILY_LOSS_LIMIT_USDT", 999.0) or 999.0)
    if cfg_dll >= 500.0 or cfg_dll > ref_cap * 0.25:
        rec_dll = round(ref_cap * float(thresholds.get("recommend_daily_loss_limit_pct_of_seed", 0.06)), 2)
        cfg["DAILY_LOSS_LIMIT_USDT"] = rec_dll
        actions.append(f"DAILY_LOSS_LIMIT_USDT: ${cfg_dll:.2f}→${rec_dll:.2f}")

    if bool(thresholds.get("require_dynamic_regime", True)) and not bool(cfg.get("USE_DYNAMIC_REGIME", False)):
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
    )
