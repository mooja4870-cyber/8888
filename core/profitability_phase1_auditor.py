#!/usr/bin/env python3
"""
8888 — Aegis V10 Profitability & Microstructure Auditor Phase 1 (`core/profitability_phase1_auditor.py`)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers literature-backed profitability diagnostics M36 ~ M38:
  - M36: Live Trade MAE / MFE, Edge Ratio (E-Ratio) & Exit Efficiency Audit (John Sweeney)
  - M37: Realized Implementation Shortfall (Slippage) & Spread / ATR Liquidity Audit
  - M38: Sequential Change-Point Early Edge Decay Detection (Page CUSUM & Reflected Wald SPRT)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import csv
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from watchdog_common import (
    BASE_8888,
    BASE_PROJECT,
    http_get_json,
)

OHLCV_CACHE_FILE = os.path.join(BASE_8888, "data", "alpha_ohlcv_cache.json")
TICKER_CACHE_FILE = os.path.join(BASE_8888, "data", "alpha_ticker_cache.json")

_OKX_BAR_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}

_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

_SIG_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?([A-Z0-9]{2,15}/USDT:USDT).*?(?:종가|entry[=:\s]+)\s*([0-9]+(?:\.[0-9]+)?)"
)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        val = float(v)
        return default if (math.isnan(val) or math.isinf(val)) else val
    except (TypeError, ValueError):
        return default


def _parse_dt(s: Any) -> Optional[datetime]:
    if not s:
        return None
    raw = str(s).strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


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
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def sym_to_okx_inst(sym: str) -> str:
    base_quote = str(sym or "").split(":")[0].strip()
    if "/" in base_quote:
        return base_quote.replace("/", "-") + "-SWAP"
    return base_quote


def sym_to_binance_inst(sym: str) -> str:
    base_quote = str(sym or "").split(":")[0].strip()
    return base_quote.replace("/", "").replace("-", "")


def _bot_exchange(bot_id: str, cfg: Optional[Dict[str, Any]] = None) -> str:
    if cfg and cfg.get("EXCHANGE_ID"):
        return str(cfg["EXCHANGE_ID"]).lower()
    return "okx" if int(bot_id) <= 8405 else "binance"


def load_paired_trades(bot_id: str, lookback_days: int = 30) -> List[Dict[str, Any]]:
    """
    Read trade_history.csv after stats.json `perf_start_time`, merge split closes sharing `주문ID`,
    and FIFO-pair `진입` with `청산` rows per symbol.
    """
    bdir = os.path.join(BASE_PROJECT, str(bot_id))
    csv_path = os.path.join(bdir, "data", "trade_history.csv")
    if not os.path.exists(csv_path):
        return []

    stats = _load_json(os.path.join(bdir, "data", "stats.json"), {}) or {}
    perf_dt = _parse_dt(stats.get("perf_start_time"))
    baselines_doc = _load_json(os.path.join(BASE_8888, "strategy_baselines.json"), {}) or {}
    strat_eff_dt = _parse_dt(((baselines_doc.get("bots") or {}).get(str(bot_id)) or {}).get("strategy_effective_since"))
    cutoff_dt = datetime.now() - timedelta(days=lookback_days) if lookback_days > 0 else None
    effective_start = perf_dt
    for cand in (strat_eff_dt, cutoff_dt):
        if cand and (effective_start is None or cand > effective_start):
            effective_start = cand

    raw_rows: List[Dict[str, Any]] = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                raw_rows.append(r)
    except Exception:
        return []

    # Parse chronologically; keep all rows after perf_start_time (not cutoff_dt) so earlier entries match later exits
    events: List[Dict[str, Any]] = []
    entry_oids = set()
    for r in raw_rows:
        dt = _parse_dt(r.get("시간") or r.get("timestamp"))
        if dt is None or (perf_dt and dt < perf_dt):
            continue
        cat = str(r.get("유형") or r.get("category") or "").strip()
        oid = str(r.get("주문ID") or r.get("order_id") or "").strip()
        if cat in ("진입", "*진입") and oid:
            entry_oids.add(oid)

    grouped_closes: Dict[Any, Dict[str, Any]] = {}
    anon_seq = 0
    for r in raw_rows:
        dt = _parse_dt(r.get("시간") or r.get("timestamp"))
        if dt is None or (perf_dt and dt < perf_dt):
            continue
        cat = str(r.get("유형") or r.get("category") or "").strip()
        sym = str(r.get("심볼") or r.get("symbol") or "").strip()
        if not sym:
            continue
        raw_side = str(r.get("방향") or r.get("side") or "").strip().lower()
        px = _safe_float(r.get("가격") or r.get("price"), 0.0)
        amt = abs(_safe_float(r.get("수량") or r.get("amount"), 0.0))
        fee = abs(_safe_float(r.get("수수료(USDT)") or r.get("fee"), 0.0))
        pnl = _safe_float(r.get("수익(USDT)") or r.get("pnl"), 0.0)
        roi_pct = _safe_float(r.get("수익률(%)") or r.get("roi_pct"), 0.0)
        lev = max(1.0, _safe_float(r.get("레버리지") or r.get("leverage"), 3.0))
        oid = str(r.get("주문ID") or r.get("order_id") or "").strip()

        if cat in ("진입", "*진입"):
            events.append({
                "kind": "entry",
                "ts": dt,
                "symbol": sym,
                "raw_side": raw_side,
                "side": "long" if raw_side == "buy" else "short",
                "price": px,
                "amount": amt,
                "fee": fee,
                "leverage": lev,
                "oid": oid,
            })
        elif "청산" in cat or cat.lower() == "close":
            if oid and oid in entry_oids and abs(pnl) <= 1e-12:
                continue
            key = (sym, oid) if oid else (sym, f"anon_{anon_seq}_{dt.isoformat()}")
            anon_seq += 1
            if key not in grouped_closes:
                grouped_closes[key] = {
                    "kind": "close",
                    "ts": dt,
                    "symbol": sym,
                    "raw_side": raw_side,
                    "px_amt": px * amt,
                    "amt": amt,
                    "fee": fee,
                    "pnl": pnl,
                    "roi_pct": roi_pct,
                    "leverage": lev,
                    "oid": oid,
                }
            else:
                g = grouped_closes[key]
                g["px_amt"] += px * amt
                g["amt"] += amt
                g["fee"] += fee
                g["pnl"] += pnl
                if dt > g["ts"]:
                    g["ts"] = dt

    for g in grouped_closes.values():
        g["price"] = (g["px_amt"] / g["amt"]) if g["amt"] > 0 else 0.0
        events.append(g)

    events.sort(key=lambda x: (x["ts"], 0 if x["kind"] == "entry" else 1))

    open_fifo: Dict[str, List[Dict[str, Any]]] = {}
    paired: List[Dict[str, Any]] = []

    for ev in events:
        sym = ev["symbol"]
        if ev["kind"] == "entry":
            open_fifo.setdefault(sym, []).append(ev)
            continue

        exit_dt = ev["ts"]
        if effective_start and exit_dt < effective_start:
            # Consume matching FIFO entry even before lookback window so state stays aligned
            if open_fifo.get(sym):
                open_fifo[sym].pop(0)
            continue

        entry_ev = open_fifo[sym].pop(0) if open_fifo.get(sym) else None
        if entry_ev and entry_ev["price"] > 0 and ev["price"] > 0:
            side = entry_ev["side"]
            entry_px = entry_ev["price"]
            exit_px = ev["price"]
            entry_dt = entry_ev["ts"]
            entry_fee = entry_ev["fee"]
            hold_h = max(0.0, (exit_dt - entry_dt).total_seconds() / 3600.0)
            realized_px_pct = ((exit_px - entry_px) / entry_px) if side == "long" else ((entry_px - exit_px) / entry_px)
        else:
            # Fallback if entry occurred prior to perf_start_time
            side = "long" if ev["raw_side"] == "sell" else "short"
            entry_px = 0.0
            exit_px = ev["price"]
            entry_dt = None
            entry_fee = 0.0
            hold_h = 0.0
            realized_px_pct = (ev["roi_pct"] / 100.0 / ev["leverage"]) if ev["roi_pct"] else 0.0

        notional = (exit_px * ev["amt"]) if (exit_px > 0 and ev["amt"] > 0) else 0.0
        total_fee = entry_fee + ev["fee"]
        net_pnl = ev["pnl"] - total_fee
        paired.append({
            "symbol": sym,
            "side": side,
            "entry_ts": entry_dt,
            "exit_ts": exit_dt,
            "hold_hours": round(hold_h, 3),
            "entry_price": entry_px,
            "exit_price": exit_px,
            "pnl": round(ev["pnl"], 6),
            "fee": round(total_fee, 6),
            "net_pnl": round(net_pnl, 6),
            "notional": round(notional, 4),
            "leverage": ev["leverage"],
            "realized_price_pct": realized_px_pct,
            "has_entry": entry_dt is not None and entry_px > 0,
        })

    return paired


def fetch_cached_klines(
    exchange: str,
    symbol: str,
    interval: str = "1h",
    limit: int = 160,
    budget_box: Optional[List[int]] = None,
    ttl_sec: int = 900,
) -> List[Dict[str, float]]:
    """Fetch OHLCV candles with 15-minute disk cache and per-cycle network fetch budget."""
    cache = _load_json(OHLCV_CACHE_FILE, {}) or {}
    key = f"{exchange}:{symbol}:{interval}"
    now = time.time()
    rec = cache.get(key)
    if isinstance(rec, dict) and (now - _safe_float(rec.get("ts"), 0.0)) < ttl_sec:
        bars = rec.get("bars") or []
        if len(bars) >= min(limit, 20):
            return bars

    if budget_box is not None:
        if budget_box[0] <= 0:
            return (rec or {}).get("bars") or []
        budget_box[0] -= 1

    bars: List[Dict[str, float]] = []
    if exchange == "binance":
        inst = sym_to_binance_inst(symbol)
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={inst}&interval={interval}&limit={limit}"
        data, _ = http_get_json(url, timeout=3.5)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, list) and len(row) >= 6:
                    bars.append({
                        "ts_ms": int(row[0]),
                        "open": _safe_float(row[1]),
                        "high": _safe_float(row[2]),
                        "low": _safe_float(row[3]),
                        "close": _safe_float(row[4]),
                        "volume": _safe_float(row[5]),
                    })
    else:
        inst = sym_to_okx_inst(symbol)
        bar_str = _OKX_BAR_MAP.get(interval, interval)
        url = f"https://www.okx.com/api/v5/market/candles?instId={inst}&bar={bar_str}&limit={min(limit, 300)}"
        data, _ = http_get_json(url, timeout=3.5)
        rows = (data or {}).get("data") if isinstance(data, dict) else None
        if isinstance(rows, list):
            for row in reversed(rows):
                if isinstance(row, list) and len(row) >= 6:
                    bars.append({
                        "ts_ms": int(row[0]),
                        "open": _safe_float(row[1]),
                        "high": _safe_float(row[2]),
                        "low": _safe_float(row[3]),
                        "close": _safe_float(row[4]),
                        "volume": _safe_float(row[5]),
                    })

    if bars:
        cache[key] = {"ts": now, "bars": bars[-max(limit, 240):]}
        # Prune stale keys (>24h)
        for ck in list(cache.keys()):
            if (now - _safe_float((cache.get(ck) or {}).get("ts"), 0.0)) > 86400:
                cache.pop(ck, None)
        _atomic_write_json(OHLCV_CACHE_FILE, cache)
        return bars
    return (rec or {}).get("bars") or []


def fetch_bulk_market_tickers(ttl_sec: int = 300) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Fetch bulk bid/ask/24h range for Binance Futures & OKX SWAP with 5-minute disk cache."""
    cache = _load_json(TICKER_CACHE_FILE, {}) or {}
    now = time.time()
    if isinstance(cache, dict) and (now - _safe_float(cache.get("ts"), 0.0)) < ttl_sec:
        if cache.get("binance") or cache.get("okx"):
            return cache

    out: Dict[str, Any] = {"ts": now, "binance": {}, "okx": {}}

    # 1) Binance bulk bookTicker + 24hr range (2 fast calls)
    b_book, _ = http_get_json("https://fapi.binance.com/fapi/v1/ticker/bookTicker", timeout=3.5)
    if isinstance(b_book, list):
        for row in b_book:
            sym_raw = str(row.get("symbol") or "")
            if sym_raw.endswith("USDT"):
                norm = f"{sym_raw[:-4]}/USDT:USDT"
                bid = _safe_float(row.get("bidPrice"))
                ask = _safe_float(row.get("askPrice"))
                if bid > 0 and ask >= bid:
                    out["binance"][norm] = {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}

    b_24h, _ = http_get_json("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=3.5)
    if isinstance(b_24h, list):
        for row in b_24h:
            sym_raw = str(row.get("symbol") or "")
            if sym_raw.endswith("USDT"):
                norm = f"{sym_raw[:-4]}/USDT:USDT"
                ent = out["binance"].setdefault(norm, {})
                ent["high24"] = _safe_float(row.get("highPrice"))
                ent["low24"] = _safe_float(row.get("lowPrice"))
                ent["last"] = _safe_float(row.get("lastPrice"))

    # 2) OKX bulk SWAP tickers (1 call includes bid/ask + 24h high/low)
    okx_tk, _ = http_get_json("https://www.okx.com/api/v5/market/tickers?instType=SWAP", timeout=3.5)
    if isinstance(okx_tk, dict) and str(okx_tk.get("code")) == "0":
        for row in (okx_tk.get("data") or []):
            inst = str(row.get("instId") or "")
            if inst.endswith("-USDT-SWAP"):
                base = inst[:-10]
                norm = f"{base}/USDT:USDT"
                bid = _safe_float(row.get("bidPx"))
                ask = _safe_float(row.get("askPx"))
                last = _safe_float(row.get("last"))
                mid = (bid + ask) / 2.0 if (bid > 0 and ask >= bid) else last
                out["okx"][norm] = {
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "last": last,
                    "high24": _safe_float(row.get("high24h")),
                    "low24": _safe_float(row.get("low24h")),
                }

    if out["binance"] or out["okx"]:
        _atomic_write_json(TICKER_CACHE_FILE, out)
        return out
    return cache if isinstance(cache, dict) else out


# ── [M36] Live MAE / MFE / Edge Ratio / Exit Efficiency Audit ───────────────────────
def audit_mae_mfe_exit_efficiency(bots: List[str]) -> Dict[str, Any]:
    """[M36] Evaluate trade path MAE, MFE, E-Ratio, and Exit Efficiency across recent paired trades."""
    alerts: List[Dict[str, str]] = []
    per_bot: Dict[str, Any] = {}
    budget = [45]

    for b in bots:
        bid = str(b)
        bdir = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(bdir, ".stopped")):
            continue
        cfg = _load_json(os.path.join(bdir, "config.json"), {}) or {}
        ex = _bot_exchange(bid, cfg)
        trades = [t for t in load_paired_trades(bid, lookback_days=14) if t["has_entry"]]
        recent = trades[-15:]

        maes: List[float] = []
        mfes: List[float] = []
        effs: List[float] = []
        winner_maes: List[float] = []
        premature_be_cnt = 0

        for tr in recent:
            sym = tr["symbol"]
            hold_h = tr["hold_hours"]
            interval = "15m" if hold_h <= 6.0 else "1h"
            bars = fetch_cached_klines(ex, sym, interval=interval, limit=160, budget_box=budget)
            entry_ms = int(tr["entry_ts"].timestamp() * 1000)
            exit_ms = int(tr["exit_ts"].timestamp() * 1000)
            bar_ms = _INTERVAL_MS.get(interval, 3_600_000)

            win_bars = [bar for bar in bars if (entry_ms - bar_ms) <= bar["ts_ms"] <= exit_ms]
            entry_px = tr["entry_price"]
            realized = tr["realized_price_pct"]
            if not win_bars or entry_px <= 0:
                continue

            max_h = max(bar["high"] for bar in win_bars)
            min_l = min(bar["low"] for bar in win_bars)
            if tr["side"] == "long":
                mae = max(0.0, (entry_px - min_l) / entry_px, -realized)
                mfe = max(0.0, (max_h - entry_px) / entry_px, realized)
            else:
                mae = max(0.0, (max_h - entry_px) / entry_px, -realized)
                mfe = max(0.0, (entry_px - min_l) / entry_px, realized)

            maes.append(mae)
            mfes.append(mfe)
            if tr["net_pnl"] > 0:
                winner_maes.append(mae)
            if mfe >= 0.004:
                effs.append(max(-1.0, min(1.2, realized / mfe)))
            if mfe >= 0.015 and realized < 0.005:
                premature_be_cnt += 1

        n_eval = len(maes)
        avg_mae = round(float(np.mean(maes)) * 100.0, 2) if maes else 0.0
        avg_mfe = round(float(np.mean(mfes)) * 100.0, 2) if mfes else 0.0
        e_ratio = round(float(np.mean(mfes)) / max(float(np.mean(maes)), 1e-4), 2) if maes else 0.0
        avg_eff = round(float(np.mean(effs)), 3) if effs else 0.0
        winner_mae_p85 = round(float(np.percentile(winner_maes, 85)) * 100.0, 2) if winner_maes else 0.0
        premature_ratio = round(premature_be_cnt / n_eval, 3) if n_eval > 0 else 0.0

        per_bot[bid] = {
            "evaluated_n": n_eval,
            "avg_mae_pct": avg_mae,
            "avg_mfe_pct": avg_mfe,
            "e_ratio": e_ratio,
            "avg_exit_efficiency": avg_eff,
            "winner_mae_p85_pct": winner_mae_p85,
            "premature_be_ratio": premature_ratio,
        }

        if n_eval >= 8 and (avg_eff < 0.35 or premature_ratio >= 0.45 or e_ratio < 0.85):
            reasons = []
            if avg_eff < 0.35:
                reasons.append(f"청산효율 {avg_eff:.2f}<0.35")
            if premature_ratio >= 0.45:
                reasons.append(f"조기본절/익절반납 {premature_ratio*100:.0f}%")
            if e_ratio < 0.85:
                reasons.append(f"E-Ratio {e_ratio:.2f}<0.85")
            alerts.append({
                "bot_id": bid,
                "key": "prof_mae_mfe_exit_eff",
                "severity": "WARN",
                "title": f"M36 MAE/MFE 청산효율 저하 ({', '.join(reasons)})",
                "details": (
                    f"최근 {n_eval}건 경로 분석: Avg MAE {avg_mae:.2f}% / Avg MFE {avg_mfe:.2f}% | "
                    f"E-Ratio {e_ratio:.2f} | 청산효율 {avg_eff:.2f} | 승자 MAE 85% 분위 {winner_mae_p85:.2f}%"
                ),
                "recommendation": "R18 본절가드/트레일링 발동선 미세 최적화 대기",
            })

    return {"per_bot": per_bot, "alerts": alerts}


# ── [M37] Realized Implementation Shortfall & Spread / ATR Liquidity Audit ──────────
def audit_slippage_and_spread_atr(bots: List[str]) -> Dict[str, Any]:
    """[M37] Measure signal-to-fill slippage (Implementation Shortfall) and Spread/ATR ratios."""
    tickers = fetch_bulk_market_tickers()
    ohlcv_cache = _load_json(OHLCV_CACHE_FILE, {}) or {}
    alerts: List[Dict[str, str]] = []
    per_bot: Dict[str, Any] = {}

    for b in bots:
        bid = str(b)
        bdir = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(bdir, ".stopped")):
            continue
        cfg = _load_json(os.path.join(bdir, "config.json"), {}) or {}
        ex = _bot_exchange(bid, cfg)
        ex_tk = tickers.get(ex) or {}
        wl = cfg.get("SYMBOL_WHITELIST") or []
        act = _load_json(os.path.join(bdir, "data", "active_positions.json"), {}) or {}
        syms = sorted(set(wl) | (set(act.keys()) if isinstance(act, dict) else set()))

        bad_symbols: List[Dict[str, Any]] = []
        spreads: List[float] = []
        for sym in syms:
            tk = ex_tk.get(sym)
            if not tk or tk.get("bid", 0.0) <= 0 or tk.get("ask", 0.0) <= 0 or tk.get("mid", 0.0) <= 0:
                continue
            mid = tk["mid"]
            spread = tk["ask"] - tk["bid"]
            spread_bps = (spread / mid) * 10000.0
            spreads.append(spread_bps)

            atr_est = 0.0
            c_rec = ohlcv_cache.get(f"{ex}:{sym}:1h") or ohlcv_cache.get(f"{ex}:{sym}:4h")
            if isinstance(c_rec, dict) and len(c_rec.get("bars") or []) >= 15:
                bs = c_rec["bars"][-15:]
                trs = [
                    max(x["high"] - x["low"], abs(x["high"] - p["close"]), abs(x["low"] - p["close"]))
                    for p, x in zip(bs[:-1], bs[1:])
                ]
                if trs:
                    atr_est = float(np.mean(trs))
            if atr_est <= 0 and tk.get("high24", 0.0) > tk.get("low24", 0.0) > 0:
                atr_est = (tk["high24"] - tk["low24"]) / 4.0
            if atr_est <= 0:
                atr_est = mid * 0.025

            spread_atr = spread / max(atr_est, 1e-9)
            if spread_bps > 15.0 or spread_atr > 0.08:
                bad_symbols.append({
                    "symbol": sym,
                    "spread_bps": round(spread_bps, 2),
                    "spread_to_atr": round(spread_atr, 4),
                    "held": sym in (act if isinstance(act, dict) else {}),
                })

        # Match recent CSV entries against bot_engine.log signal prices (within +-180s)
        sig_points: Dict[str, List[Tuple[datetime, float]]] = {}
        log_path = os.path.join(bdir, "bot_engine.log")
        if os.path.exists(log_path):
            try:
                with open(log_path, "rb") as lf:
                    lf.seek(0, os.SEEK_END)
                    lf.seek(max(0, lf.tell() - 524288))
                    txt = lf.read().decode("utf-8", errors="ignore")
                for ln in txt.splitlines():
                    m = _SIG_LOG_RE.search(ln)
                    if m:
                        dt = _parse_dt(m.group(1))
                        px = _safe_float(m.group(3), 0.0)
                        if dt and px > 0:
                            sig_points.setdefault(m.group(2), []).append((dt, px))
            except Exception:
                pass

        is_list: List[float] = []
        trades = [t for t in load_paired_trades(bid, lookback_days=7) if t["has_entry"]]
        for tr in trades[-25:]:
            pts = sig_points.get(tr["symbol"]) or []
            if not pts:
                continue
            best_dt_diff = 181.0
            best_sig_px = 0.0
            for s_dt, s_px in pts:
                diff = abs((tr["entry_ts"] - s_dt).total_seconds())
                if diff <= 180.0 and diff < best_dt_diff:
                    best_dt_diff = diff
                    best_sig_px = s_px
            if best_sig_px > 0 and tr["entry_price"] > 0:
                sign = 1.0 if tr["side"] == "long" else -1.0
                is_bps = sign * (tr["entry_price"] - best_sig_px) / best_sig_px * 10000.0
                if abs(is_bps) < 300.0:
                    is_list.append(is_bps)

        avg_spread_bps = round(float(np.mean(spreads)), 2) if spreads else 0.0
        avg_is_bps = round(float(np.mean(is_list)), 2) if is_list else 0.0
        per_bot[bid] = {
            "avg_spread_bps": avg_spread_bps,
            "illiquid_symbols": bad_symbols,
            "is_sample_n": len(is_list),
            "avg_is_bps": avg_is_bps,
        }

        if bad_symbols or (len(is_list) >= 3 and avg_is_bps > 12.0):
            sym_desc = ", ".join(f"{x['symbol']}({x['spread_bps']}bps)" for x in bad_symbols[:4])
            msg_parts = []
            if bad_symbols:
                msg_parts.append(f"고스프레드/저유동성 {len(bad_symbols)}종목 [{sym_desc}]")
            if len(is_list) >= 3 and avg_is_bps > 12.0:
                msg_parts.append(f"실전 슬리피지 {avg_is_bps:+.1f}bps>{12.0}bps (N={len(is_list)})")
            alerts.append({
                "bot_id": bid,
                "key": "prof_slippage_spread_atr",
                "severity": "WARN",
                "title": f"M37 체결 슬리피지·스프레드 비효율 ({' / '.join(msg_parts)})",
                "details": f"평균 스프레드 {avg_spread_bps:.2f}bps | 실전 IS {avg_is_bps:+.2f}bps (N={len(is_list)})",
                "recommendation": "R19 비유동성 종목 화이트리스트 제외 검토",
            })

    return {"per_bot": per_bot, "alerts": alerts}


# ── [M38] CUSUM & Reflected SPRT Sequential Edge Decay Audit ────────────────────────
def audit_cusum_sprt_edge_decay(bots: List[str], baselines_doc: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """[M38] Sequential change-point edge decay detection using one-sided CUSUM and reflected SPRT."""
    alerts: List[Dict[str, str]] = []
    per_bot: Dict[str, Any] = {}
    bl_bots = (baselines_doc or {}).get("bots") or {}
    sprt_limit = math.log(0.90 / 0.05)  # ~2.8904 (alpha=0.05, beta=0.10)

    for b in bots:
        bid = str(b)
        bdir = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(bdir, ".stopped")):
            continue

        trades = load_paired_trades(bid, lookback_days=60)[-40:]
        n = len(trades)
        if n < 12:
            per_bot[bid] = {"n": n, "cusum": 0.0, "sprt": 0.0, "status": "collecting"}
            continue

        net_pnls = [tr["net_pnl"] for tr in trades]
        losses = [abs(x) for x in net_pnls if x < 0]
        if len(losses) >= 2:
            r_scale = max(float(np.median(losses)), 0.01)
        else:
            r_scale = max(float(np.median([abs(x) for x in net_pnls])), 0.01)

        r_mults = [max(-5.0, min(5.0, x / r_scale)) for x in net_pnls]

        # Downward CUSUM on R-multiples (target mu0=+0.15R, slack k=0.25R)
        cusum = 0.0
        cusum_max = 0.0
        for r in r_mults:
            cusum = max(0.0, cusum + (0.15 - r) - 0.25)
            cusum_max = max(cusum_max, cusum)

        # Reflected Gaussian SPRT: H0: mu0=+0.20*sigma vs H1: mu1=-0.25*sigma
        sigma = max(float(np.std(r_mults)), 0.35)
        mu0 = 0.20 * sigma
        mu1 = -0.25 * sigma
        sprt = 0.0
        sprt_max = 0.0
        for r in r_mults:
            llr = ((mu1 - mu0) * (r - 0.5 * (mu0 + mu1))) / (sigma ** 2)
            sprt = max(0.0, sprt + llr)
            sprt_max = max(sprt_max, sprt)

        pf = 0.0
        gw = sum(x for x in net_pnls if x > 0)
        gl = abs(sum(x for x in net_pnls if x < 0))
        pf = round(gw / gl, 2) if gl > 0 else (9.99 if gw > 0 else 0.0)

        cusum_r = round(cusum, 3)
        sprt_r = round(sprt, 3)
        bl_pf = _safe_float(((bl_bots.get(bid) or {}).get("backtest") or {}).get("net_pf"), 1.15)

        per_bot[bid] = {
            "n": n,
            "r_scale_usdt": round(r_scale, 4),
            "avg_r": round(float(np.mean(r_mults)), 3),
            "pf": pf,
            "baseline_pf": bl_pf,
            "cusum": cusum_r,
            "cusum_max": round(cusum_max, 3),
            "sprt": sprt_r,
            "sprt_threshold": round(sprt_limit, 3),
        }

        if cusum_r >= 7.5 and sprt_r >= sprt_limit:
            sev = "CRITICAL"
        elif cusum_r >= 4.5 or sprt_r >= sprt_limit:
            sev = "WARN"
        else:
            sev = ""

        if sev:
            alerts.append({
                "bot_id": bid,
                "key": "prof_cusum_sprt_decay",
                "severity": sev,
                "title": f"M38 순차 알파 감쇠 조기경보 (CUSUM {cusum_r:.2f} / SPRT {sprt_r:.2f})",
                "details": (
                    f"최근 {n}건 변화점 탐지: CUSUM={cusum_r:.2f} (경계 3.5/5.0), "
                    f"SPRT={sprt_r:.2f} (경계 {sprt_limit:.2f}), 실전 PF={pf:.2f} (기대 {bl_pf:.2f})"
                ),
                "recommendation": "R20 알파 감쇠 선제 비중 감축·동적레짐 방어 연동",
            })

    return {"per_bot": per_bot, "alerts": alerts}
