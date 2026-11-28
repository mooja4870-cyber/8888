#!/usr/bin/env python3
"""
8888 — Aegis V10 Profitability & Microstructure Auditor Phase 3 (`core/profitability_phase3_auditor.py`)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers portfolio-level allocation, positioning crowding & counterfactual alpha M41, M42, M44:
  - M41: Open Interest (OI) Velocity & Perp-Spot Basis Crowding Risk Audit
  - M42: Live Cross-Bot Correlation Spike Detection & Pure-NumPy HRP Risk Budgeting (Carver / López de Prado)
  - M44: Counterfactual Shadow Signal Opportunity Cost & Post-Exit Price Drift Audit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import numpy as np

from core.profitability_phase1_auditor import (
    _atomic_write_json,
    _bot_exchange,
    _load_json,
    _parse_dt,
    _safe_float,
    fetch_bulk_market_tickers,
    load_paired_trades,
    sym_to_binance_inst,
    sym_to_okx_inst,
)
from watchdog_common import (
    BASE_8888,
    BASE_PROJECT,
    http_get_json,
)

OI_CACHE_FILE = os.path.join(BASE_8888, "data", "alpha_oi_cache.json")
OI_HISTORY_FILE = os.path.join(BASE_8888, "data", "alpha_oi_history.json")
SHADOW_TRACKER_FILE = os.path.join(BASE_8888, "data", "alpha_shadow_tracker.json")
SNAPSHOTS_PATH = os.path.join(BASE_8888, "snapshots.json")

_BREAKOUT_BOTS = {"8402", "8405", "8407", "8410"}
_MEAN_REV_BOTS = {"8403"}

_BLOCKED_SIG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?([A-Z0-9]{2,15}/USDT:USDT).*?"
    r"\b(LONG|SHORT|long|short)\b.*?(신호 강도 부족|쿨다운|이격|최대 포지션|거래량 미달|ADX)"
)
_PRICE_HINT_RE = re.compile(r"(?:종가|price|entry)[=:\s]+([0-9]+(?:\.[0-9]+)?)", re.I)


# ── [M41] Open Interest Velocity & Perp-Spot Basis Crowding Audit ───────────────────
def audit_oi_basis_crowding(bots: List[str]) -> Dict[str, Any]:
    """[M41] Track perp-spot mark/index basis bps and OI Z-score across held/breakout symbols."""
    cache = _load_json(OI_CACHE_FILE, {}) or {}
    now = time.time()
    use_cached = isinstance(cache, dict) and (now - _safe_float(cache.get("ts"), 0.0)) < 600

    # Collect held symbols + representative top symbols (cap 15)
    held_by_bot: Dict[str, List[str]] = {}
    held_syms = set()
    for b in bots:
        bid = str(b)
        bdir = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(bdir, ".stopped")):
            continue
        act = _load_json(os.path.join(bdir, "data", "active_positions.json"), {}) or {}
        if isinstance(act, dict):
            syms = sorted(act.keys())
            held_by_bot[bid] = syms
            held_syms.update(syms)

    focus_syms = list(sorted(held_syms))
    for maj in ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT", "BNB/USDT:USDT"):
        if maj not in held_syms and len(focus_syms) < 15:
            focus_syms.append(maj)
    focus_syms = focus_syms[:15]

    sym_metrics: Dict[str, Dict[str, Any]] = (cache.get("symbols") or {}) if use_cached else {}
    if not use_cached or not sym_metrics:
        sym_metrics = {}
        # 1) Binance bulk premiumIndex (markPrice vs indexPrice -> basis_bps)
        b_basis: Dict[str, float] = {}
        b_prem, _ = http_get_json("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=3.5)
        if isinstance(b_prem, list):
            for row in b_prem:
                raw_sym = str(row.get("symbol") or "")
                if raw_sym.endswith("USDT"):
                    mark = _safe_float(row.get("markPrice"))
                    idx = _safe_float(row.get("indexPrice"))
                    if mark > 0 and idx > 0:
                        b_basis[f"{raw_sym[:-4]}/USDT:USDT"] = ((mark - idx) / idx) * 10000.0

        # 2) Binance Open Interest for focus symbols (capped <= 15)
        oi_hist = _load_json(OI_HISTORY_FILE, {}) or {}
        for sym in focus_syms:
            inst = sym_to_binance_inst(sym)
            oi_res, _ = http_get_json(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={inst}", timeout=3.0)
            oi_val = _safe_float((oi_res or {}).get("openInterest"), 0.0) if isinstance(oi_res, dict) else 0.0
            basis_bps = round(b_basis.get(sym, 0.0), 2)

            if oi_val <= 0:
                okx_inst = sym_to_okx_inst(sym)
                okx_oi, _ = http_get_json(f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={okx_inst}", timeout=3.0)
                okx_rows = (okx_oi or {}).get("data") if isinstance(okx_oi, dict) else None
                if isinstance(okx_rows, list) and okx_rows:
                    oi_val = _safe_float(okx_rows[0].get("oi"), 0.0)

            hist_list = [
                h for h in (oi_hist.get(sym) or [])
                if isinstance(h, dict) and (now - _safe_float(h.get("ts"), 0.0)) <= 7 * 86400
            ]
            if oi_val > 0:
                if not hist_list or (now - _safe_float(hist_list[-1].get("ts"), 0.0)) >= 240:
                    hist_list.append({"ts": now, "oi": oi_val})
                oi_hist[sym] = hist_list[-500:]

            oi_z = 0.0
            oi_24h_chg = 0.0
            vals = [_safe_float(h.get("oi")) for h in hist_list if _safe_float(h.get("oi")) > 0]
            if len(vals) >= 6:
                mu = float(np.mean(vals[:-1]))
                sd = float(np.std(vals[:-1]))
                if sd > 1e-9:
                    oi_z = round((vals[-1] - mu) / sd, 2)
                old_24 = [h["oi"] for h in hist_list if (now - _safe_float(h.get("ts"), 0.0)) >= 72000]
                if old_24 and old_24[-1] > 0:
                    oi_24h_chg = round(((vals[-1] - old_24[-1]) / old_24[-1]) * 100.0, 2)

            crowded = (abs(basis_bps) > 35.0) or (oi_z > 2.5)
            sym_metrics[sym] = {
                "basis_bps": basis_bps,
                "oi": round(oi_val, 2),
                "oi_zscore": oi_z,
                "oi_24h_chg_pct": oi_24h_chg,
                "crowded": crowded,
            }

        _atomic_write_json(OI_HISTORY_FILE, oi_hist)
        _atomic_write_json(OI_CACHE_FILE, {"ts": now, "symbols": sym_metrics})

    crowded_list = [s for s, m in sym_metrics.items() if m.get("crowded")]
    alerts: List[Dict[str, str]] = []
    per_bot: Dict[str, Any] = {}

    for b in bots:
        bid = str(b)
        bdir = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(bdir, ".stopped")):
            continue
        held = held_by_bot.get(bid, [])
        held_crowded = [s for s in held if s in crowded_list]
        role = "breakout" if bid in _BREAKOUT_BOTS else ("mean_rev" if bid in _MEAN_REV_BOTS else "hybrid")
        per_bot[bid] = {
            "role": role,
            "held_crowded": held_crowded,
            "favorable_crowding_mr": bool(role == "mean_rev" and crowded_list),
        }
        if role == "breakout" and held_crowded:
            desc = ", ".join(
                f"{s}(basis={sym_metrics[s]['basis_bps']:+.1f}bps, OI_Z={sym_metrics[s]['oi_zscore']:+.1f})"
                for s in held_crowded[:3]
            )
            alerts.append({
                "bot_id": bid,
                "key": "prof_oi_basis_crowding",
                "severity": "WARN",
                "title": f"M41 추격돌파 봇 과열 포지션 감지 ({len(held_crowded)}종목)",
                "details": f"OI/베이시스 과열 구간 보유: {desc}",
                "recommendation": "R23 추격 과열 쿨다운 보수화 연동",
            })

    return {
        "symbols": sym_metrics,
        "crowded_symbols": crowded_list,
        "per_bot": per_bot,
        "alerts": alerts,
    }


# ── [M42] Live Correlation Spike & Pure-NumPy HRP Dynamic Risk Budget ───────────────
def _pure_hrp_weights(cov: np.ndarray, corr: np.ndarray) -> np.ndarray:
    """Pure-NumPy Hierarchical Risk Parity (single-linkage distance order + recursive bisection)."""
    n = corr.shape[0]
    if n == 0:
        return np.array([])
    if n == 1:
        return np.array([1.0])

    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)

    # Simple pure-Python single-linkage agglomerative tree -> leaf seriation
    clusters: Dict[int, List[int]] = {i: [i] for i in range(n)}
    next_id = n
    active_ids = list(range(n))
    cur_dist = dist.copy()
    id_to_idx = {i: i for i in range(n)}

    while len(active_ids) > 1:
        best_pair = (active_ids[0], active_ids[1])
        best_d = float("inf")
        for i_pos in range(len(active_ids)):
            ci = active_ids[i_pos]
            ii = id_to_idx[ci]
            for j_pos in range(i_pos + 1, len(active_ids)):
                cj = active_ids[j_pos]
                jj = id_to_idx[cj]
                if cur_dist[ii, jj] < best_d:
                    best_d = cur_dist[ii, jj]
                    best_pair = (ci, cj)
        c1, c2 = best_pair
        clusters[next_id] = clusters[c1] + clusters[c2]
        idx1, idx2 = id_to_idx[c1], id_to_idx[c2]
        # Single-linkage update into idx1 slot
        for ck in active_ids:
            if ck not in (c1, c2):
                ik = id_to_idx[ck]
                d_new = min(cur_dist[idx1, ik], cur_dist[idx2, ik])
                cur_dist[idx1, ik] = d_new
                cur_dist[ik, idx1] = d_new
        active_ids.remove(c2)
        active_ids[active_ids.index(c1)] = next_id
        id_to_idx[next_id] = idx1
        next_id += 1

    sort_ix = clusters[active_ids[0]]
    weights = np.ones(n, dtype=float)
    items = [sort_ix]

    def _cluster_var(sub_idx: List[int]) -> float:
        sub_cov = cov[np.ix_(sub_idx, sub_idx)]
        diag = np.clip(np.diag(sub_cov), 1e-10, None)
        ivp = (1.0 / diag)
        ivp /= np.sum(ivp)
        return float(ivp @ sub_cov @ ivp)

    while items:
        next_items: List[List[int]] = []
        for sub in items:
            if len(sub) <= 1:
                continue
            mid = len(sub) // 2
            left, right = sub[:mid], sub[mid:]
            v_left = max(_cluster_var(left), 1e-10)
            v_right = max(_cluster_var(right), 1e-10)
            alpha = 1.0 - v_left / (v_left + v_right)
            for idx in left:
                weights[idx] *= alpha
            for idx in right:
                weights[idx] *= (1.0 - alpha)
            if len(left) > 1:
                next_items.append(left)
            if len(right) > 1:
                next_items.append(right)
        items = next_items

    s = float(np.sum(weights))
    return weights / s if s > 0 else np.ones(n) / n


def _load_bot_daily_returns(bot_id: str) -> Dict[str, float]:
    """Build {YYYY-MM-DD: daily_ret} from snapshots.json, equity_curve.json, or trade_history.csv."""
    bdir = os.path.join(BASE_PROJECT, bot_id)
    daily_bal: Dict[str, float] = {}

    # 1) Equity curve JSON
    eq_path = os.path.join(bdir, "data", "equity_curve.json")
    eq_rows = _load_json(eq_path, [])
    if isinstance(eq_rows, list):
        for pt in eq_rows:
            if isinstance(pt, dict) and pt.get("ts") and pt.get("balance"):
                ts = _safe_float(pt.get("ts"))
                bal = _safe_float(pt.get("balance"))
                if ts > 0 and bal > 0:
                    dstr = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                    daily_bal[dstr] = bal

    # 2) Augment from 8888 snapshots.json (which covers up to current day)
    snaps = _load_json(SNAPSHOTS_PATH, [])
    if isinstance(snaps, list):
        for sn in snaps[-360:]:
            if not isinstance(sn, dict):
                continue
            dt = _parse_dt(sn.get("ts"))
            bmap = sn.get("bots") or {}
            ent = bmap.get(bot_id)
            if dt and isinstance(ent, dict):
                bal = _safe_float(ent.get("ex_balance") or ent.get("asset") or 0.0)
                if bal > 0:
                    daily_bal[dt.strftime("%Y-%m-%d")] = bal

    if len(daily_bal) >= 4:
        days = sorted(daily_bal.keys())
        rets: Dict[str, float] = {}
        for d0, d1 in zip(days[:-1], days[1:]):
            b0, b1 = daily_bal[d0], daily_bal[d1]
            if b0 > 0:
                rets[d1] = (b1 - b0) / b0
        return rets

    # 3) Fallback: daily CSV PnL / initial seed
    stats = _load_json(os.path.join(bdir, "data", "stats.json"), {}) or {}
    seed = max(_safe_float(stats.get("seed_money"), 10.0), 1.0)
    by_day: Dict[str, float] = {}
    for tr in load_paired_trades(bot_id, lookback_days=30):
        dstr = tr["exit_ts"].strftime("%Y-%m-%d")
        by_day[dstr] = by_day.get(dstr, 0.0) + tr["net_pnl"]
    return {d: pnl / seed for d, pnl in by_day.items()}


def audit_live_correlation_and_hrp_budget(bots: List[str]) -> Dict[str, Any]:
    """[M42] Detect live multi-bot return correlation spikes and compute HRP risk weights."""
    active_bots = [
        str(b) for b in bots
        if not os.path.exists(os.path.join(BASE_PROJECT, str(b), ".stopped"))
    ]
    ret_maps = {bid: _load_bot_daily_returns(bid) for bid in active_bots}
    all_days = sorted({d for rm in ret_maps.values() for d in rm.keys()})[-30:]

    valid_bots = [bid for bid in active_bots if len(ret_maps[bid]) >= 5]
    alerts: List[Dict[str, str]] = []
    if len(valid_bots) < 2 or len(all_days) < 5:
        return {
            "common_days": len(all_days),
            "avg_corr": 0.0,
            "hrp_weights": {b: round(1.0 / max(len(active_bots), 1), 4) for b in active_bots},
            "recommended_risk_pct": {},
            "alerts": [],
        }

    mat = np.array([[ret_maps[bid].get(d, 0.0) for bid in valid_bots] for d in all_days], dtype=float)
    # Keep columns with non-zero variance
    stds = np.std(mat, axis=0)
    nz_idx = [i for i, s in enumerate(stds) if s > 1e-8]
    common_days = len(all_days)

    if len(nz_idx) < 2:
        eq_w = round(1.0 / len(active_bots), 4)
        return {
            "common_days": common_days,
            "avg_corr": 0.0,
            "hrp_weights": {b: eq_w for b in active_bots},
            "recommended_risk_pct": {b: 0.01 for b in active_bots},
            "alerts": [],
        }

    nz_bots = [valid_bots[i] for i in nz_idx]
    sub_mat = mat[:, nz_idx]
    corr = np.corrcoef(sub_mat, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    cov = np.cov(sub_mat, rowvar=False)
    cov = np.nan_to_num(cov, nan=1e-8)

    m = len(nz_bots)
    off_diag = [corr[i, j] for i in range(m) for j in range(m) if i != j]
    avg_corr = round(float(np.mean(off_diag)), 3) if off_diag else 0.0

    hrp_w_nz = _pure_hrp_weights(cov, corr)
    ann_vols = {nz_bots[i]: round(float(np.std(sub_mat[:, i]) * math.sqrt(365.0) * 100.0), 2) for i in range(m)}

    hrp_weights: Dict[str, float] = {}
    rec_risk: Dict[str, float] = {}
    base_weight = 1.0 / max(m, 1)
    for idx, bid in enumerate(nz_bots):
        w = float(hrp_w_nz[idx])
        hrp_weights[bid] = round(w, 4)
        # Map relative HRP weight smoothly around M4 baseline 1.0% (clamped 0.6%~1.5%)
        scaled = 0.01 * (w / base_weight)
        if avg_corr > 0.55:
            scaled *= 0.85
        rec_risk[bid] = round(max(0.006, min(0.015, scaled)), 4)

    for bid in active_bots:
        if bid not in hrp_weights:
            hrp_weights[bid] = round(1.0 / len(active_bots), 4)
            rec_risk[bid] = 0.01

    if common_days >= 7 and avg_corr > 0.70:
        sev = "CRITICAL"
    elif common_days >= 7 and avg_corr > 0.55:
        sev = "WARN"
    else:
        sev = ""

    if sev:
        top_alloc = ", ".join(f"{b}:{w*100:.1f}%" for b, w in sorted(hrp_weights.items(), key=lambda x: -x[1])[:4])
        alerts.append({
            "bot_id": "8888",
            "key": "prof_corr_spike_hrp",
            "severity": sev,
            "title": f"M42 플릿 상관관계 급등 (평균 상관 ρ={avg_corr:.2f})",
            "details": f"{common_days}일 기준 {m}봇 평균 상관계수 {avg_corr:.3f} | HRP 권장 비중 상위: {top_alloc}",
            "recommendation": "R22 상관 급등 시 플릿 리스크 예산 일괄 압축 연동",
        })

    return {
        "common_days": common_days,
        "evaluated_bots": nz_bots,
        "avg_corr": avg_corr,
        "ann_vol_pct": ann_vols,
        "hrp_weights": hrp_weights,
        "recommended_risk_pct": rec_risk,
        "alerts": alerts,
    }


# ── [M44] Counterfactual Shadow Signal & Post-Exit Price Drift Audit ────────────────
def audit_shadow_signals_and_post_exit_drift(bots: List[str]) -> Dict[str, Any]:
    """[M44] Track blocked signal counterfactual returns and post-exit drift at +4h/+12h/+24h."""
    tracker = _load_json(SHADOW_TRACKER_FILE, {}) or {}
    if not isinstance(tracker, dict):
        tracker = {}
    blocked_items: List[Dict[str, Any]] = tracker.get("blocked") or []
    exit_items: List[Dict[str, Any]] = tracker.get("exits") or []

    now = time.time()
    seen_blocked = {(x.get("bot_id"), x.get("symbol"), x.get("ts")) for x in blocked_items if isinstance(x, dict)}
    seen_exits = {(x.get("bot_id"), x.get("symbol"), x.get("ts")) for x in exit_items if isinstance(x, dict)}

    tickers = fetch_bulk_market_tickers()
    live_prices: Dict[Tuple[str, str], float] = {}
    for ex_name in ("binance", "okx"):
        for sym, row in (tickers.get(ex_name) or {}).items():
            px = _safe_float(row.get("mid") or row.get("last"), 0.0)
            if px > 0:
                live_prices[(ex_name, sym)] = px

    # 1) Ingest newly blocked signals & newly closed trades
    for b in bots:
        bid = str(b)
        bdir = os.path.join(BASE_PROJECT, bid)
        if os.path.exists(os.path.join(bdir, ".stopped")):
            continue
        cfg = _load_json(os.path.join(bdir, "config.json"), {}) or {}
        ex = _bot_exchange(bid, cfg)

        # Fallback prices from scan_results.json
        scan_doc = _load_json(os.path.join(bdir, "scan_results.json"), {}) or {}
        for srow in (scan_doc.get("results") or []):
            if isinstance(srow, dict) and srow.get("symbol") and _safe_float(srow.get("price")) > 0:
                live_prices.setdefault((ex, srow["symbol"]), _safe_float(srow["price"]))

        log_path = os.path.join(bdir, "bot_engine.log")
        if os.path.exists(log_path):
            try:
                with open(log_path, "rb") as lf:
                    lf.seek(0, os.SEEK_END)
                    lf.seek(max(0, lf.tell() - 262144))
                    lines = lf.read().decode("utf-8", errors="ignore").splitlines()
                for ln in lines:
                    m = _BLOCKED_SIG_RE.search(ln)
                    if not m:
                        continue
                    dt = _parse_dt(m.group(1))
                    if not dt:
                        continue
                    ts_val = dt.timestamp()
                    if (now - ts_val) > 14 * 86400:
                        continue
                    sym = m.group(2)
                    side = m.group(3).lower()
                    ftag = m.group(4)
                    pm = _PRICE_HINT_RE.search(ln)
                    px = _safe_float(pm.group(1), 0.0) if pm else live_prices.get((ex, sym), 0.0)
                    key = (bid, sym, round(ts_val, 0))
                    if px > 0 and key not in seen_blocked:
                        seen_blocked.add(key)
                        blocked_items.append({
                            "bot_id": bid,
                            "exchange": ex,
                            "symbol": sym,
                            "side": side,
                            "filter": ftag,
                            "ts": round(ts_val, 0),
                            "price": px,
                        })
            except Exception:
                pass

        for tr in load_paired_trades(bid, lookback_days=7)[-20:]:
            ex_ts = round(tr["exit_ts"].timestamp(), 0)
            key = (bid, tr["symbol"], ex_ts)
            if tr["exit_price"] > 0 and key not in seen_exits:
                seen_exits.add(key)
                exit_items.append({
                    "bot_id": bid,
                    "exchange": ex,
                    "symbol": tr["symbol"],
                    "side": tr["side"],
                    "ts": ex_ts,
                    "price": tr["exit_price"],
                })

    # 2) Evaluate matured horizons (4h, 12h, 24h) & prune >14d
    def _eval_list(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        kept = []
        for it in items:
            if not isinstance(it, dict):
                continue
            age = now - _safe_float(it.get("ts"), 0.0)
            if age > 14 * 86400:
                continue
            cur_px = live_prices.get((it.get("exchange", "binance"), it.get("symbol", "")), 0.0)
            base_px = _safe_float(it.get("price"), 0.0)
            if cur_px > 0 and base_px > 0:
                sign = 1.0 if it.get("side") == "long" else -1.0
                ret_pct = sign * ((cur_px - base_px) / base_px) * 100.0
                for h_lbl, h_sec in (("ret_4h_pct", 14400), ("ret_12h_pct", 43200), ("ret_24h_pct", 86400)):
                    if age >= h_sec and h_lbl not in it:
                        it[h_lbl] = round(ret_pct, 3)
            kept.append(it)
        return kept[-1000:]

    blocked_items = _eval_list(blocked_items)
    exit_items = _eval_list(exit_items)
    _atomic_write_json(SHADOW_TRACKER_FILE, {"updated": now, "blocked": blocked_items, "exits": exit_items})

    alerts: List[Dict[str, str]] = []
    per_bot: Dict[str, Any] = {}
    for b in bots:
        bid = str(b)
        b_blk = [x for x in blocked_items if x.get("bot_id") == bid and "ret_4h_pct" in x]
        b_ext = [x for x in exit_items if x.get("bot_id") == bid and "ret_4h_pct" in x]

        shadow_rets = [x["ret_4h_pct"] for x in b_blk]
        gw = sum(r for r in shadow_rets if r > 0)
        gl = abs(sum(r for r in shadow_rets if r < 0))
        shadow_pf = round(gw / gl, 2) if gl > 0 else (9.99 if gw > 0 else 0.0)
        shadow_wr = round((sum(1 for r in shadow_rets if r > 0) / len(shadow_rets)) * 100.0, 1) if shadow_rets else 0.0

        fcounts: Dict[str, int] = {}
        for x in b_blk:
            ft = str(x.get("filter") or "unknown")
            fcounts[ft] = fcounts.get(ft, 0) + 1
        dom_filter = max(fcounts, key=fcounts.get) if fcounts else None

        exit_drifts = [x["ret_4h_pct"] for x in b_ext]
        med_drift = round(float(np.median(exit_drifts)), 2) if exit_drifts else 0.0

        # Compare against recent live PF
        live_trades = load_paired_trades(bid, lookback_days=14)
        lgw = sum(t["net_pnl"] for t in live_trades if t["net_pnl"] > 0)
        lgl = abs(sum(t["net_pnl"] for t in live_trades if t["net_pnl"] < 0))
        live_pf = round(lgw / lgl, 2) if lgl > 0 else (9.99 if lgw > 0 else 0.0)

        per_bot[bid] = {
            "shadow_eval_n": len(shadow_rets),
            "shadow_pf_4h": shadow_pf,
            "shadow_wr_4h_pct": shadow_wr,
            "dominant_filter": dom_filter,
            "exit_drift_n": len(exit_drifts),
            "median_post_exit_drift_4h_pct": med_drift,
            "live_pf_14d": live_pf,
        }

        opp_hit = (len(shadow_rets) >= 10 and shadow_pf > 1.35 and live_pf < 1.0)
        drift_hit = (len(exit_drifts) >= 10 and med_drift > 1.5)
        if opp_hit or drift_hit:
            reasons = []
            if opp_hit:
                reasons.append(f"탈락 시그널 4h 가상 PF {shadow_pf:.2f}>1.35 (주원인: {dom_filter})")
            if drift_hit:
                reasons.append(f"청산후 +4h 동일방향 표류 중앙값 +{med_drift:.2f}%")
            alerts.append({
                "bot_id": bid,
                "key": "prof_shadow_opp_cost",
                "severity": "WARN",
                "title": f"M44 미진입 기회비용·조기청산 표류 감지 ({' / '.join(reasons)})",
                "details": f"섀도우 표본 {len(shadow_rets)}건 (가상승률 {shadow_wr:.1f}% vs 실전PF {live_pf:.2f}), 청산후표류 {len(exit_drifts)}건",
                "recommendation": "R23 과도 필터 완화 및 익절 여유폭 점검 연동",
                "meta": {"opp_hit": opp_hit, "drift_hit": drift_hit, "dominant_filter": dom_filter},
            })

    return {"per_bot": per_bot, "alerts": alerts}
