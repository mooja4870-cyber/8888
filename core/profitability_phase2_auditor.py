#!/usr/bin/env python3
"""
8888 — Aegis V10 Profitability & Microstructure Auditor Phase 2 (`core/profitability_phase2_auditor.py`)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers perpetual-futures & regime profitability diagnostics M39, M40, M43:
  - M39: Cumulative Funding Carry Attribution & Settlement Window (00/08/16 UTC) Whipsaw Audit
  - M40: Intraday Session (Asia/Europe/US/Late) & Weekend Liquidity Seasonality Attribution
  - M43: Long/Short Directional Expectancy Skew & BTC 4h EMA200 Regime Alignment Audit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import numpy as np

from core.profitability_phase1_auditor import (
    _atomic_write_json,
    _bot_exchange,
    _load_json,
    _safe_float,
    fetch_cached_klines,
    load_paired_trades,
    sym_to_okx_inst,
)
from watchdog_common import (
    BASE_8888,
    BASE_PROJECT,
    http_get_json,
)

FUNDING_CACHE_FILE = os.path.join(BASE_8888, "data", "alpha_funding_cache.json")


def fetch_bulk_funding_rates(bots: List[str], ttl_sec: int = 600) -> Dict[str, Dict[str, float]]:
    """Fetch current Binance & OKX perpetual funding rates with 10-minute disk cache."""
    cache = _load_json(FUNDING_CACHE_FILE, {}) or {}
    now = time.time()
    if isinstance(cache, dict) and (now - _safe_float(cache.get("ts"), 0.0)) < ttl_sec:
        if cache.get("binance") or cache.get("okx"):
            return cache

    out: Dict[str, Any] = {"ts": now, "binance": {}, "okx": {}}

    # 1) Binance bulk premiumIndex (single call returns fundingRate for all USDT swaps)
    b_prem, _ = http_get_json("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=3.5)
    if isinstance(b_prem, list):
        for row in b_prem:
            raw_sym = str(row.get("symbol") or "")
            if raw_sym.endswith("USDT"):
                norm = f"{raw_sym[:-4]}/USDT:USDT"
                out["binance"][norm] = _safe_float(row.get("lastFundingRate"), 0.0)

    # 2) OKX active/recent symbols (capped at 12 calls)
    okx_syms = set()
    for b in bots:
        bid = str(b)
        bdir = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(bdir, ".stopped")):
            continue
        cfg = _load_json(os.path.join(bdir, "config.json"), {}) or {}
        if _bot_exchange(bid, cfg) != "okx":
            continue
        act = _load_json(os.path.join(bdir, "data", "active_positions.json"), {}) or {}
        if isinstance(act, dict):
            okx_syms.update(act.keys())
        for tr in load_paired_trades(bid, lookback_days=14)[-10:]:
            okx_syms.add(tr["symbol"])

    for sym in sorted(okx_syms)[:12]:
        inst = sym_to_okx_inst(sym)
        data, _ = http_get_json(f"https://www.okx.com/api/v5/public/funding-rate?instId={inst}", timeout=3.0)
        rows = (data or {}).get("data") if isinstance(data, dict) else None
        if isinstance(rows, list) and rows:
            out["okx"][sym] = _safe_float(rows[0].get("fundingRate"), 0.0)

    if out["binance"] or out["okx"]:
        _atomic_write_json(FUNDING_CACHE_FILE, out)
        return out
    return cache if isinstance(cache, dict) else out


# ── [M39] Funding Carry Attribution & Settlement Window Whipsaw ─────────────────────
def audit_funding_carry_and_settlement_whipsaw(bots: List[str]) -> Dict[str, Any]:
    """[M39] Separate cumulative funding carry PnL and inspect 00/08/16 UTC settlement whipsaw."""
    rates_doc = fetch_bulk_funding_rates(bots)
    alerts: List[Dict[str, str]] = []
    per_bot: Dict[str, Any] = {}

    for b in bots:
        bid = str(b)
        bdir = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(bdir, ".stopped")):
            continue
        cfg = _load_json(os.path.join(bdir, "config.json"), {}) or {}
        ex = _bot_exchange(bid, cfg)
        ex_rates = rates_doc.get(ex) or {}
        fallback_rates = rates_doc.get("binance") or {}

        trades = [t for t in load_paired_trades(bid, lookback_days=30) if t["has_entry"]]
        est_funding_pnl = 0.0
        gross_price_pnl = 0.0
        total_crossings = 0
        settlement_pnls: List[float] = []

        for tr in trades:
            gross_price_pnl += tr["pnl"]
            rate = ex_rates.get(tr["symbol"], fallback_rates.get(tr["symbol"], 0.0001))
            entry_ep = int(tr["entry_ts"].timestamp())
            exit_ep = int(tr["exit_ts"].timestamp())
            crossings = max(0, (exit_ep // 28800) - (entry_ep // 28800))
            total_crossings += crossings
            sign = 1.0 if tr["side"] == "long" else -1.0
            notional = tr["notional"] if tr["notional"] > 0 else 10.0
            est_funding_pnl += (-sign * notional * rate * crossings)

            mod = entry_ep % 28800
            dist_to_settle = min(mod, 28800 - mod)
            if dist_to_settle <= 300:
                settlement_pnls.append(tr["net_pnl"])

        base_profit = max(abs(gross_price_pnl), 0.05)
        funding_drag_pct = round((-est_funding_pnl / base_profit) * 100.0, 2) if est_funding_pnl < 0 else 0.0

        set_n = len(settlement_pnls)
        set_gw = sum(x for x in settlement_pnls if x > 0)
        set_gl = abs(sum(x for x in settlement_pnls if x < 0))
        set_pf = round(set_gw / set_gl, 2) if set_gl > 0 else (9.99 if set_gw > 0 else 0.0)
        set_wr = round((sum(1 for x in settlement_pnls if x > 0) / set_n) * 100.0, 1) if set_n > 0 else 0.0

        per_bot[bid] = {
            "trades_30d": len(trades),
            "funding_crossings": total_crossings,
            "gross_price_pnl": round(gross_price_pnl, 4),
            "est_funding_pnl": round(est_funding_pnl, 4),
            "funding_drag_pct": funding_drag_pct,
            "settlement_window_n": set_n,
            "settlement_pf": set_pf,
            "settlement_wr_pct": set_wr,
        }

        drain_hit = (est_funding_pnl < -0.05 and funding_drag_pct > 15.0)
        settle_hit = (set_n >= 5 and set_pf < 0.70)
        if drain_hit or settle_hit:
            parts = []
            if drain_hit:
                parts.append(f"누적 펀딩 유출 ${est_funding_pnl:+.3f} (비중 {funding_drag_pct:.1f}%)")
            if settle_hit:
                parts.append(f"정산±5분 진입 PF {set_pf:.2f} (N={set_n})")
            alerts.append({
                "bot_id": bid,
                "key": "prof_funding_carry_drain",
                "severity": "WARN",
                "title": f"M39 펀딩비 캐리 유출/정산 휩쏘 ({' / '.join(parts)})",
                "details": (
                    f"30일 펀딩 정산 {total_crossings}회 통과: 가격PnL ${gross_price_pnl:+.3f}, "
                    f"추정펀딩PnL ${est_funding_pnl:+.3f}, 정산±5분 승률 {set_wr:.1f}%"
                ),
                "recommendation": "R21 불리 펀딩·정산 시각 진입 억제 연동",
            })

    return {"per_bot": per_bot, "alerts": alerts}


# ── [M40] Intraday Session & Weekend Liquidity Seasonality ──────────────────────────
def _bucket_stats(rows: List[Dict[str, Any]], r_scale: float) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0, "wr_pct": 0.0, "pf": 0.0, "net_pnl": 0.0, "avg_r": 0.0}
    pnls = [r["net_pnl"] for r in rows]
    wins = sum(1 for x in pnls if x > 0)
    gw = sum(x for x in pnls if x > 0)
    gl = abs(sum(x for x in pnls if x < 0))
    pf = round(gw / gl, 2) if gl > 0 else (9.99 if gw > 0 else 0.0)
    return {
        "n": n,
        "wr_pct": round((wins / n) * 100.0, 1),
        "pf": pf,
        "net_pnl": round(sum(pnls), 4),
        "avg_r": round(float(np.mean([x / r_scale for x in pnls])), 3),
    }


def audit_intraday_weekend_seasonality(bots: List[str]) -> Dict[str, Any]:
    """[M40] Decompose bot expectancy across Asia/Europe/US/Late UTC sessions & Weekday/Weekend."""
    alerts: List[Dict[str, str]] = []
    per_bot: Dict[str, Any] = {}

    for b in bots:
        bid = str(b)
        bdir = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(bdir, ".stopped")):
            continue

        trades = load_paired_trades(bid, lookback_days=30)
        losses = [abs(t["net_pnl"]) for t in trades if t["net_pnl"] < 0]
        r_scale = max(float(np.median(losses)) if losses else 0.01, 0.01)

        sessions: Dict[str, List[Dict[str, Any]]] = {
            "ASIA_00_08": [],
            "EUROPE_08_13": [],
            "US_OPEN_13_20": [],
            "LATE_US_20_24": [],
        }
        day_types: Dict[str, List[Dict[str, Any]]] = {
            "WEEKDAY": [],
            "WEEKEND": [],
        }

        for tr in trades:
            ref_dt = tr["entry_ts"] or tr["exit_ts"]
            if ref_dt is None:
                continue
            utc_dt = datetime.fromtimestamp(ref_dt.timestamp(), tz=timezone.utc)
            hr = utc_dt.hour
            if hr < 8:
                sessions["ASIA_00_08"].append(tr)
            elif hr < 13:
                sessions["EUROPE_08_13"].append(tr)
            elif hr < 20:
                sessions["US_OPEN_13_20"].append(tr)
            else:
                sessions["LATE_US_20_24"].append(tr)

            wd = utc_dt.weekday()  # Mon=0 .. Sat=5, Sun=6
            is_wknd = (wd == 5) or (wd == 6 and hr < 20)
            day_types["WEEKEND" if is_wknd else "WEEKDAY"].append(tr)

        sess_res = {k: _bucket_stats(v, r_scale) for k, v in sessions.items()}
        day_res = {k: _bucket_stats(v, r_scale) for k, v in day_types.items()}
        bleeding_buckets = [
            f"{k}(N={st['n']}, PF={st['pf']:.2f}, ${st['net_pnl']:+.2f})"
            for k, st in {**sess_res, **day_res}.items()
            if st["n"] >= 15 and st["pf"] < 0.80 and st["net_pnl"] < 0
        ]

        per_bot[bid] = {
            "sessions": sess_res,
            "day_types": day_res,
            "bleeding_buckets": bleeding_buckets,
        }

        if bleeding_buckets:
            alerts.append({
                "bot_id": bid,
                "key": "prof_session_seasonality",
                "severity": "WARN",
                "title": f"M40 시간대·주말 유동성 손실 구간 감지 ({len(bleeding_buckets)}구간)",
                "details": "30일 세션 분해 손실 구간: " + ", ".join(bleeding_buckets),
                "recommendation": "R21 취약 시간대 진입 억제(쿨다운 상향) 연동",
            })

    return {"per_bot": per_bot, "alerts": alerts}


# ── [M43] Long / Short Directional Expectancy Skew & Macro Alignment ────────────────
def audit_directional_expectancy_skew(bots: List[str]) -> Dict[str, Any]:
    """[M43] Compare LONG vs SHORT expectancy, win rate, PF, and BTC 4h EMA200 regime alignment."""
    alerts: List[Dict[str, str]] = []
    per_bot: Dict[str, Any] = {}

    btc_trend = 0
    btc_bars = fetch_cached_klines("binance", "BTC/USDT:USDT", interval="4h", limit=220, budget_box=[1])
    if len(btc_bars) >= 202:
        closes = [x["close"] for x in btc_bars[:-1]]
        alpha = 2.0 / (200.0 + 1.0)
        ema = closes[0]
        for c in closes[1:]:
            ema = alpha * c + (1.0 - alpha) * ema
        btc_trend = 1 if closes[-1] > ema else -1

    def _side_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        n = len(rows)
        if n == 0:
            return {"n": 0, "wr_pct": 0.0, "pf": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "net_pnl": 0.0, "avg_hold_h": 0.0}
        pnls = [r["net_pnl"] for r in rows]
        wins = [x for x in pnls if x > 0]
        losses = [abs(x) for x in pnls if x < 0]
        gw = sum(wins)
        gl = sum(losses)
        pf = round(gw / gl, 2) if gl > 0 else (9.99 if gw > 0 else 0.0)
        return {
            "n": n,
            "wr_pct": round((len(wins) / n) * 100.0, 1),
            "pf": pf,
            "avg_win": round(float(np.mean(wins)), 4) if wins else 0.0,
            "avg_loss": round(float(np.mean(losses)), 4) if losses else 0.0,
            "net_pnl": round(sum(pnls), 4),
            "avg_hold_h": round(float(np.mean([r["hold_hours"] for r in rows])), 2),
        }

    for b in bots:
        bid = str(b)
        bdir = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(bdir, ".stopped")):
            continue

        trades = load_paired_trades(bid, lookback_days=60)
        longs = [t for t in trades if t["side"] == "long"]
        shorts = [t for t in trades if t["side"] == "short"]
        ls = _side_stats(longs)
        ss = _side_stats(shorts)
        n_tot = len(trades)

        weak_side = None
        skew_reason = ""
        if ls["n"] >= 12 and ss["n"] >= 12:
            if ls["pf"] < 0.75 and ss["pf"] > 1.20:
                weak_side = "long"
                skew_reason = f"LONG 편향 손실(PF {ls['pf']:.2f} vs SHORT {ss['pf']:.2f})"
            elif ss["pf"] < 0.75 and ls["pf"] > 1.20:
                weak_side = "short"
                skew_reason = f"SHORT 편향 손실(PF {ss['pf']:.2f} vs LONG {ls['pf']:.2f})"

        per_bot[bid] = {
            "btc_4h_ema200_trend": btc_trend,
            "long": ls,
            "short": ss,
            "weak_side": weak_side,
        }

        if weak_side:
            alerts.append({
                "bot_id": bid,
                "key": "prof_dir_expectancy_skew",
                "severity": "WARN",
                "title": f"M43 방향성 비대칭 기대값 경고 ({skew_reason})",
                "details": (
                    f"60일 방향 분해: LONG N={ls['n']} PF={ls['pf']:.2f} (${ls['net_pnl']:+.2f}) | "
                    f"SHORT N={ss['n']} PF={ss['pf']:.2f} (${ss['net_pnl']:+.2f}) | BTC 4h 추세={btc_trend:+d}"
                ),
                "recommendation": "R21 방향 비대칭 보정 및 동적레짐 보호 연동",
            })

    return {"btc_4h_ema200_trend": btc_trend, "per_bot": per_bot, "alerts": alerts}
