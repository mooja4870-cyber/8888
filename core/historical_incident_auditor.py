#!/usr/bin/env python3
"""
8888 — Aegis V10.5 Historical Incident Gap-Closing Auditor (`core/historical_incident_auditor.py`)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers the 6 historical operational blind spots M45 ~ M50 identified across 8401~8410 & 8888 history:
  - M45: Individual Bot Streamlit UI HTTP 200, Log SyntaxError & Passive Overwrite Antipattern Audit
  - M46: Identity Safety (.env Duplicate API Key SHA256 Check, Key↔Exchange Mismatch & Cross-Exchange Symbols)
  - M47: Fleet Registry Parity, seed_money Validity & peak_assets ATH Lag Detection
  - M48: Config Hazards (USE_WEBSOCKET=True, Small-Account EQUITY_SCALE_FACTOR<1.0, Stale Recovered Halt)
  - M49: Scanner Silent Drop (scan_results.json Count Drop <50% or Zero-Volume Ticker Bug)
  - M50: 8888 Control App Liveness ([DISCORD 1MIN] >10m Stall, Stale app.py/discord_alert.py, HTTP Down)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.profitability_phase1_auditor import (
    _atomic_write_json,
    _load_json,
    _safe_float,
    fetch_bulk_market_tickers,
)
from watchdog_common import (
    BASE_8888,
    BASE_PROJECT,
    is_external_network_down,
    load_proactive_alerts,
)

HISTORICAL_AUDIT_FILE = os.path.join(BASE_8888, "data", "historical_audit_health.json")
PEAK_ASSETS_FILE = os.path.join(BASE_8888, "peak_assets.json")
SENTINEL_CACHE_FILE = os.path.join(BASE_8888, "data", "sentinel_live_cache.json")
LIFECYCLE_STATUS_FILE = os.path.join(BASE_8888, "data", "lifecycle_status.json")
BASELINES_FILE = os.path.join(BASE_8888, "strategy_baselines.json")

_PASSIVE_OVERWRITE_RE = re.compile(
    r"if\s+selected_tf\s*!=\s*current_tf\s*:[\s\S]{0,240}save_config"
)
_DISCORD_1MIN_RE = re.compile(r"\[DISCORD 1MIN\]\s+(\d{2}:\d{2}:\d{2})\s+ok=True")


def _active_bot_dirs(bots: List[Any]) -> List[str]:
    out = []
    for b in bots:
        bs = str(b)
        bdir = os.path.join(BASE_PROJECT, bs)
        if os.path.isdir(bdir) and not os.path.exists(os.path.join(bdir, ".stopped")):
            out.append(bs)
    return out


_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _local_http_status(url: str, timeout: float = 3.0) -> int:
    req = urllib.request.Request(url, method="GET")
    with _DIRECT_OPENER.open(req, timeout=timeout) as resp:
        return int(getattr(resp, "status", 200) or 200)


# ── [M45] Bot UI HTTP 200, Log Errors & Passive Overwrite Audit ──────────────────────
def check_ui_health_and_passive_overwrite(bots: List[Any]) -> Dict[str, Any]:
    """[M45] Check individual bot UI HTTP 200 liveness, UI log syntax errors, and passive overwrite."""
    alerts: List[Dict[str, Any]] = []
    per_bot: Dict[str, Any] = {}

    for bid in _active_bot_dirs(bots):
        bdir = os.path.join(BASE_PROJECT, bid)
        http_ok = False
        http_code = 0
        if bid.isdigit():
            try:
                http_code = _local_http_status(f"http://127.0.0.1:{bid}", timeout=3.0)
                http_ok = (http_code == 200)
            except Exception:
                http_ok = False

        ui_log_err = False
        st_log = os.path.join(bdir, "streamlit_server.log")
        if os.path.exists(st_log):
            try:
                with open(st_log, "rb") as lf:
                    lf.seek(0, os.SEEK_END)
                    lf.seek(max(0, lf.tell() - 16384))
                    txt = lf.read().decode("utf-8", errors="ignore").lower()
                clean = "\n".join(
                    ln for ln in txt.splitlines()
                    if not any(x in ln for x in ("websocketclosederror", "streamclosederror", "tornado/websocket.py", "tornado/iostream.py"))
                )
                if "syntaxerror" in clean or "indentationerror" in clean:
                    ui_log_err = True
            except Exception:
                pass

        passive_ow = False
        app_path = os.path.join(bdir, "app.py")
        if os.path.exists(app_path):
            try:
                with open(app_path, "r", encoding="utf-8", errors="ignore") as f:
                    if _PASSIVE_OVERWRITE_RE.search(f.read()):
                        passive_ow = True
            except Exception:
                pass

        per_bot[bid] = {
            "http_ok": http_ok,
            "http_code": http_code,
            "ui_log_err": ui_log_err,
            "passive_overwrite": passive_ow,
        }

        if (not http_ok) or ui_log_err:
            alerts.append({
                "bot_id": bid,
                "key": "hist_ui_down",
                "severity": "WARN",
                "title": f"M45 개별 봇 UI 장애 감지 (포트 {bid} HTTP={http_code})",
                "details": f"Streamlit UI 응답={http_code}, 로그구문오류={ui_log_err} (매매엔진 무관 UI 단독 재기동 필요)",
                "recommendation": "R24 bot.py 무중단 UI 단독 재기동 연동",
            })
        if passive_ow:
            alerts.append({
                "bot_id": bid,
                "key": "hist_ui_passive_overwrite",
                "severity": "INFO",
                "title": "M45 UI Passive Overwrite 안티패턴 감지",
                "details": "app.py 내 selected_tf != current_tf 시 자동 save_config 패턴 존재 (구형 세션 캐시 역덮어쓰기 위험)",
                "recommendation": "[코드 점검] on_change 콜백 전용 격리 권고",
            })

    return {"per_bot": per_bot, "alerts": alerts}


# ── [M46] Identity Safety (.env Duplicate Key) & Cross-Exchange Whitelist Audit ──────
def _parse_env_keys(env_path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.exists(env_path):
        return out
    try:
        with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
            for ln in f:
                s = ln.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if v:
                    out[k] = v
    except Exception:
        pass
    return out


def check_identity_and_cross_exchange_symbols(bots: List[Any]) -> Dict[str, Any]:
    """[M46] Audit .env key fingerprints (never storing raw secrets) and cross-exchange symbols."""
    alerts: List[Dict[str, Any]] = []
    per_bot: Dict[str, Any] = {}
    key_owners: Dict[str, List[str]] = {}

    tickers = fetch_bulk_market_tickers(ttl_sec=600)

    for bid in _active_bot_dirs(bots):
        bdir = os.path.join(BASE_PROJECT, bid)
        cfg = _load_json(os.path.join(bdir, "config.json"), {}) or {}
        ex = str(cfg.get("EXCHANGE_ID", "okx" if int(bid) <= 8405 else "binance")).lower()
        env_map = _parse_env_keys(os.path.join(bdir, ".env"))

        expected_var = "OKX_API_KEY" if ex == "okx" else "BINANCE_API_KEY"
        other_var = "BINANCE_API_KEY" if ex == "okx" else "OKX_API_KEY"
        raw_key = env_map.get(expected_var, "")
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:10] if raw_key else ""
        key_mismatch = bool((not raw_key) and env_map.get(other_var))

        if key_hash:
            key_owners.setdefault(f"{ex}:{key_hash}", []).append(bid)

        ex_markets = set((tickers.get(ex) or {}).keys())
        wl = cfg.get("SYMBOL_WHITELIST") or []
        bad_syms: List[str] = []
        if len(ex_markets) >= 50 and isinstance(wl, list):
            for sym in wl:
                if isinstance(sym, str) and sym not in ex_markets:
                    bad_syms.append(sym)

        per_bot[bid] = {
            "exchange": ex,
            "key_fp": key_hash,
            "key_mismatch": key_mismatch,
            "cross_exchange_symbols": bad_syms,
        }

        if key_mismatch:
            alerts.append({
                "bot_id": bid,
                "key": "hist_duplicate_api_key",
                "severity": "CRITICAL",
                "title": f"M46 .env API 키↔거래소({ex}) 불일치 감지",
                "details": f"config.json은 {ex}이나 .env에 {expected_var} 부재 및 타거래소 키 존재",
                "recommendation": "[외부 계정/OS 개입 필요] .env API 키 정합화 필요",
            })

        if bad_syms:
            alerts.append({
                "bot_id": bid,
                "key": "hist_cross_exchange_symbol",
                "severity": "WARN",
                "title": f"M46 타거래소·미상장 심볼 혼입 ({len(bad_syms)}종목)",
                "details": f"{ex} 마켓 미상장 화이트리스트 종목: {', '.join(bad_syms[:6])}",
                "recommendation": "R25 타거래소 미상장 종목 자동 제외 연동",
                "meta": {"bad_symbols": bad_syms},
            })

    dups = {k: owners for k, owners in key_owners.items() if len(owners) > 1}
    for kfp, owners in dups.items():
        is_shared_binance = kfp.startswith("binance:")
        alerts.append({
            "bot_id": "8888",
            "key": "hist_duplicate_api_key",
            "severity": "INFO" if is_shared_binance else "CRITICAL",
            "title": f"M46 복수 봇 간 동일 API 키 중복 감지 ({', '.join(owners)})",
            "details": f"키 지문 {kfp}가 {owners}에서 공동 사용 중 — {'단일 바이낸스 공용계정 운용(교차 포지션 주의)' if is_shared_binance else '교차 계좌/포지션 침범 위험'}",
            "recommendation": "[정보] 바이낸스 공용계정 운용 중(동일 심볼 동시진입 주의)" if is_shared_binance else "[외부 계정/OS 개입 필요] 봇별 독립 계좌 API 키 분리 필요",
        })

    return {"per_bot": per_bot, "duplicate_keys": dups, "alerts": alerts}


# ── [M47] Fleet Registry Parity, seed_money & peak_assets ATH Sync ──────────────────
def check_fleet_registry_and_peak_seed_integrity(bots: List[Any]) -> Dict[str, Any]:
    """[M47] Verify all active 84xx dirs are registered and detect seed_money<=0 or peak_assets lag."""
    alerts: List[Dict[str, Any]] = []
    reg_set = {str(b) for b in bots}
    baselines = (_load_json(BASELINES_FILE, {}) or {}).get("bots") or {}
    prof_active = set()
    prof_path = os.path.join(BASE_8888, "watchdog_profitability.py")
    if os.path.exists(prof_path):
        try:
            txt = open(prof_path, "r", encoding="utf-8", errors="ignore").read()
            m = re.search(r"ACTIVE_BOTS\s*=\s*\[([^\]]+)\]", txt)
            if m:
                prof_active = set(re.findall(r'"(\d{4})"', m.group(1)))
        except Exception:
            pass

    missing_registry: List[str] = []
    for d in sorted(glob.glob(os.path.join(BASE_PROJECT, "84*"))):
        if not os.path.isdir(d) or "backup" in os.path.basename(d):
            continue
        if os.path.exists(os.path.join(d, ".stopped")):
            continue
        bid = os.path.basename(d)
        if bid not in reg_set or bid not in baselines or (prof_active and bid not in prof_active):
            missing_registry.append(bid)

    peak_doc = _load_json(PEAK_ASSETS_FILE, {}) or {}
    live_cache = (_load_json(SENTINEL_CACHE_FILE, {}) or {}).get("bots") or {}
    now = time.time()

    seed_issues: List[str] = []
    peak_lag: Dict[str, float] = {}
    for bid in _active_bot_dirs(bots):
        stats = _load_json(os.path.join(BASE_PROJECT, bid, "data", "stats.json"), {}) or {}
        seed = _safe_float(stats.get("seed_money"), 0.0)
        if seed <= 0.0:
            seed_issues.append(f"{bid}(seed={seed})")
        cent = live_cache.get(bid)
        if isinstance(cent, dict) and (now - _safe_float(cent.get("ts"), 0.0)) <= 900:
            live_bal = _safe_float(cent.get("balance"), 0.0)
            pk_val = _safe_float((peak_doc.get(bid) or {}).get("peak_asset"), 0.0)
            if live_bal > 0 and live_bal > pk_val * 1.005:
                peak_lag[bid] = round(live_bal, 4)

    if missing_registry:
        alerts.append({
            "bot_id": "8888",
            "key": "hist_registry_or_peak_drift",
            "severity": "WARN",
            "title": f"M47 신규/활성 봇 관제·기준선 등록 누락 ({', '.join(missing_registry)})",
            "details": f"워치독/strategy_baselines.json 미등록 활성 봇: {', '.join(missing_registry)}",
            "recommendation": "BOT_LIST·ACTIVE_BOTS·strategy_baselines.json 등록 동기화 필요",
        })
    if seed_issues:
        alerts.append({
            "bot_id": "8888",
            "key": "hist_registry_or_peak_drift",
            "severity": "WARN",
            "title": f"M47 봇 기준자본(seed_money) 이상 ({', '.join(seed_issues)})",
            "details": f"seed_money <= 0 감지: {', '.join(seed_issues)}",
            "recommendation": "stats.json seed_money 정합화 확인 필요",
        })
    if peak_lag:
        desc = ", ".join(f"{b}:${v:.2f}" for b, v in peak_lag.items())
        alerts.append({
            "bot_id": "8888",
            "key": "hist_registry_or_peak_drift",
            "severity": "INFO",
            "title": f"M47 peak_assets 고점 갱신 지연 ({len(peak_lag)}봇)",
            "details": f"실잔고가 기록된 peak_asset를 상회함: {desc}",
            "recommendation": "R26 peak_assets.json 상향 동기화 연동",
            "meta": {"peak_lag": peak_lag},
        })

    return {
        "missing_registry": missing_registry,
        "seed_issues": seed_issues,
        "peak_lag": peak_lag,
        "alerts": alerts,
    }


# ── [M48] Config Hazards (WS=True, Small EQUITY_SCALE, Stale Halt) ──────────────────
def check_config_hazards_and_stale_halt(bots: List[Any]) -> Dict[str, Any]:
    """[M48] Detect USE_WEBSOCKET=True, EQUITY_SCALE_FACTOR<1 on small equity, and stale AUTO_TRADING=False."""
    alerts: List[Dict[str, Any]] = []
    per_bot: Dict[str, Any] = {}
    live_cache = (_load_json(SENTINEL_CACHE_FILE, {}) or {}).get("bots") or {}
    lifecycle = (_load_json(LIFECYCLE_STATUS_FILE, {}) or {}).get("bots") or {}
    active_pa = (load_proactive_alerts().get("active") or {})
    blackswan_on = any(
        str((v or {}).get("alert_key") or "") == "blackswan_usdt_depeg"
        for v in active_pa.values()
    )

    for bid in _active_bot_dirs(bots):
        cfg = _load_json(os.path.join(BASE_PROJECT, bid, "config.json"), {}) or {}
        stats = _load_json(os.path.join(BASE_PROJECT, bid, "data", "stats.json"), {}) or {}
        bal = _safe_float((live_cache.get(bid) or {}).get("balance"), _safe_float(stats.get("seed_money"), 10.0))

        hazards: List[str] = []
        if cfg.get("USE_WEBSOCKET") is True:
            hazards.append("use_websocket_true")

        eq_scale = _safe_float(cfg.get("EQUITY_SCALE_FACTOR"), 1.0)
        if bal > 0 and bal < 20.0 and eq_scale < 0.99:
            hazards.append("small_account_equity_scale_lt1")

        if cfg.get("AUTO_TRADING") is False and (not blackswan_on):
            lc = lifecycle.get(bid) or {}
            dd_pct = abs(_safe_float(lc.get("peak_dd_pct"), 0.0))
            mdd_kill = _safe_float(lc.get("peak_mdd_kill_pct"), 22.0)
            # Flag only if drawdown is safely below 75% of kill threshold
            if mdd_kill > 0 and dd_pct < mdd_kill * 0.75:
                hazards.append("stale_auto_trading_false")

        per_bot[bid] = {"balance": round(bal, 2), "eq_scale": eq_scale, "hazards": hazards}
        if hazards:
            alerts.append({
                "bot_id": bid,
                "key": "hist_config_hazard",
                "severity": "WARN",
                "title": f"M48 잠재 설정 위험 감지 ({', '.join(hazards)})",
                "details": f"잔고=${bal:.2f}, EQUITY_SCALE={eq_scale}, WS={cfg.get('USE_WEBSOCKET')}, AUTO={cfg.get('AUTO_TRADING')}",
                "recommendation": "R27 안전 설정 자동 정규화 연동",
                "meta": {"hazards": hazards},
            })

    return {"per_bot": per_bot, "alerts": alerts}


# ── [M49] Scanner Silent Drop (0 Results or Zero-Volume Bug) ────────────────────────
def check_scanner_silent_drop(bots: List[Any]) -> Dict[str, Any]:
    """[M49] Detect silent scanner degradation where results drop <50% or volume_m==0."""
    alerts: List[Dict[str, Any]] = []
    per_bot: Dict[str, Any] = {}

    for bid in _active_bot_dirs(bots):
        bdir = os.path.join(BASE_PROJECT, bid)
        cfg = _load_json(os.path.join(bdir, "config.json"), {}) or {}
        wl = cfg.get("SYMBOL_WHITELIST") or []
        wl_n = len(wl) if isinstance(wl, list) else 0
        scan = _load_json(os.path.join(bdir, "scan_results.json"), {}) or {}
        results = scan.get("results") if isinstance(scan, dict) else None

        if not isinstance(results, list):
            per_bot[bid] = {"status": "missing_results"}
            continue

        n_res = len(results)
        has_vol_m = any(isinstance(r, dict) and ("volume_m" in r) for r in results)
        zero_vol = sum(1 for r in results if isinstance(r, dict) and _safe_float(r.get("volume_m"), 0.0) <= 0.0) if has_vol_m else 0
        zero_vol_ratio = (zero_vol / n_res) if (has_vol_m and n_res > 0) else 0.0

        drop_hit = (wl_n >= 6 and n_res < max(3, int(wl_n * 0.5)))
        vol_hit = (has_vol_m and n_res >= 5 and zero_vol_ratio >= 0.50)

        per_bot[bid] = {
            "wl_n": wl_n,
            "scan_n": n_res,
            "zero_vol_ratio": round(zero_vol_ratio, 3),
            "silent_drop": bool(drop_hit or vol_hit),
        }

        if drop_hit or vol_hit:
            reasons = []
            if drop_hit:
                reasons.append(f"스캔결과 {n_res}/{wl_n}종목(<50%)")
            if vol_hit:
                reasons.append(f"거래대금 0 표기 비율 {zero_vol_ratio*100:.0f}%")
            alerts.append({
                "bot_id": bid,
                "key": "hist_scanner_silent_drop",
                "severity": "WARN",
                "title": f"M49 스캐너 부분 침묵 장애 ({', '.join(reasons)})",
                "details": f"scan_results.json 항목={n_res}, 화이트리스트={wl_n}, volume_m=0 비율={zero_vol_ratio*100:.0f}%",
                "recommendation": "R28 스캐너 침묵 봇 안전 재기동 연동",
            })

    return {"per_bot": per_bot, "alerts": alerts}


# ── [M50] 8888 Control App & Discord 1-Min Thread Liveness ──────────────────────────
def check_8888_app_and_discord_liveness() -> Dict[str, Any]:
    """[M50] Check 8888 app.py HTTP liveness, stale code vs process start, and [DISCORD 1MIN] beat."""
    alerts: List[Dict[str, Any]] = []
    now = time.time()
    app_log = os.path.join(BASE_8888, "app.log")
    last_discord_age: Optional[float] = None

    if os.path.exists(app_log):
        try:
            with open(app_log, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                lines = f.read().decode("utf-8", errors="ignore").splitlines()
            for ln in reversed(lines):
                m = _DISCORD_1MIN_RE.search(ln)
                if m:
                    hh, mm, ss = (int(x) for x in m.group(1).split(":"))
                    now_dt = datetime.now()
                    cand = now_dt.replace(hour=hh, minute=mm, second=ss, microsecond=0)
                    diff = (now_dt - cand).total_seconds()
                    if diff < -3600:
                        diff += 86400
                    last_discord_age = round(max(0.0, diff), 1)
                    break
        except Exception:
            pass

    stale_files: List[str] = []
    pid_out = subprocess.run(["pgrep", "-f", ".*8888/app.py"], capture_output=True, text=True)
    app_pids = [p.strip() for p in pid_out.stdout.splitlines() if p.strip().isdigit()]
    if app_pids:
        try:
            lstart = subprocess.check_output(["ps", "-p", app_pids[0], "-o", "lstart="], text=True, timeout=3).strip()
            proc_dt = datetime.strptime(lstart, "%a %b %d %H:%M:%S %Y")
            proc_ts = proc_dt.timestamp()
            for fname in ("app.py", "discord_alert.py"):
                fpath = os.path.join(BASE_8888, fname)
                if os.path.exists(fpath) and os.path.getmtime(fpath) > proc_ts + 120.0:
                    stale_files.append(fname)
        except Exception:
            pass

    http_ok = False
    try:
        http_ok = (_local_http_status("http://127.0.0.1:8888/api/alpha_report", timeout=4.0) == 200)
    except Exception:
        http_ok = False

    if not http_ok:
        alerts.append({
            "bot_id": "8888",
            "key": "hist_8888_app_stale_or_discord_halt",
            "severity": "CRITICAL",
            "title": "M50 8888 중앙 관제 웹서버 응답 불가",
            "details": "http://127.0.0.1:8888/api/alpha_report 응답 실패 (프로세스 중단 또는 행 상태)",
            "recommendation": "R29 8888 app.py 안전 재기동 연동",
            "meta": {"reason": "app_8888_http_down"},
        })
    elif stale_files:
        alerts.append({
            "bot_id": "8888",
            "key": "hist_8888_app_stale_or_discord_halt",
            "severity": "WARN",
            "title": f"M50 8888 app.py Stale 코드 감지 ({', '.join(stale_files)})",
            "details": f"소스 수정({', '.join(stale_files)}) 이후 8888/app.py 미재기동 상태",
            "recommendation": "R29 8888 app.py 안전 재기동 연동",
            "meta": {"reason": "app_8888_stale_code"},
        })
    elif (last_discord_age is not None) and last_discord_age > 600.0 and (not is_external_network_down()):
        alerts.append({
            "bot_id": "8888",
            "key": "hist_8888_app_stale_or_discord_halt",
            "severity": "WARN",
            "title": f"M50 8888 1분 디스코드 요약 발송 정지 ({int(last_discord_age)}초 경과)",
            "details": f"app.log 마지막 [DISCORD 1MIN] ok=True 이후 {int(last_discord_age)}초(>600초) 경과",
            "recommendation": "R29 8888 app.py 안전 재기동 연동",
            "meta": {"reason": "discord_1min_stalled"},
        })

    return {
        "http_ok": http_ok,
        "app_pids": app_pids,
        "stale_files": stale_files,
        "last_discord_age_sec": last_discord_age,
        "alerts": alerts,
    }


def run_historical_incident_audit(bots: List[Any]) -> Dict[str, Any]:
    """Run all 6 historical blind-spot auditors M45~M50 and persist snapshot JSON."""
    t0 = time.time()
    errors: Dict[str, str] = {}
    alerts: List[Dict[str, Any]] = []

    def _safe(name: str, fn, *args) -> Dict[str, Any]:
        try:
            res = fn(*args) or {}
            alerts.extend(res.get("alerts") or [])
            return res
        except Exception as exc:
            errors[name] = str(exc)
            return {"alerts": [], "error": str(exc)}

    m45 = _safe("M45", check_ui_health_and_passive_overwrite, bots)
    m46 = _safe("M46", check_identity_and_cross_exchange_symbols, bots)
    m47 = _safe("M47", check_fleet_registry_and_peak_seed_integrity, bots)
    m48 = _safe("M48", check_config_hazards_and_stale_halt, bots)
    m49 = _safe("M49", check_scanner_silent_drop, bots)
    m50 = _safe("M50", check_8888_app_and_discord_liveness)

    payload = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "modules": ["M45", "M46", "M47", "M48", "M49", "M50"],
        "errors": errors,
        "m45_ui_health": m45,
        "m46_identity_symbols": m46,
        "m47_registry_peak": m47,
        "m48_config_hazards": m48,
        "m49_scanner_drop": m49,
        "m50_8888_liveness": m50,
        "alerts": alerts,
    }
    _atomic_write_json(HISTORICAL_AUDIT_FILE, payload)
    return payload
