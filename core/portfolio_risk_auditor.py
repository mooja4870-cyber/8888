#!/usr/bin/env python3
"""
8888 — Portfolio Risk, TCA, Alpha Decay & Scorecard Auditor (`core/portfolio_risk_auditor.py`)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Covers Aegis V6 modules (Read-Only evaluation + alert/scorecard, NEVER mutates bot configs):
  - M16: Cross-Bot Portfolio Gross/Net Exposure, Same-Symbol Directional Crowding & 24h Fleet Drawdown
  - M21: Transaction Cost Analysis (Realized Fee bps vs Baseline Cost) + Stale Open Orders + Dust
  - M22: Early Alpha Decay (Rolling 30-trade Binomial Z-score & Profit Factor) + BTC Regime Volatility Shock
  - M26: Unified Health Scorecard (0~100) + KST 08:00 Daily Briefing (Discord + Telegram)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import csv
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from watchdog_common import (
    BASE_8888,
    BASE_PROJECT,
    _send_discord,
    _send_telegram,
    http_get_json,
    load_proactive_alerts,
)

SENTINEL_CACHE_FILE = os.path.join(BASE_8888, "data", "sentinel_live_cache.json")
BASELINES_FILE = os.path.join(BASE_8888, "strategy_baselines.json")
SNAPSHOTS_FILE = os.path.join(BASE_8888, "snapshots.json")
SCORECARD_FILE = os.path.join(BASE_8888, "data", "watchdog_scorecard.json")
INFRA_HEALTH_FILE = os.path.join(BASE_8888, "data", "infra_health.json")
HEARTBEAT_FILE = os.path.join(BASE_8888, "data", "watchdog_heartbeat.json")


def _load_json(path: str, default: Any = None) -> Any:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _atomic_write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_dt(s: str) -> Optional[datetime]:
    txt = str(s or "").strip()
    if len(txt) < 19:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(txt[:19].replace("T", " "), fmt)
        except ValueError:
            continue
    return None


def _load_grouped_closed_trades(bot_id: str) -> List[Dict[str, Any]]:
    """Load merged closed trades after perf_start_time sorted chronologically."""
    bdir = os.path.join(BASE_PROJECT, bot_id)
    csv_path = os.path.join(bdir, "data", "trade_history.csv")
    if not os.path.exists(csv_path):
        return []
    stats = _load_json(os.path.join(bdir, "data", "stats.json"), {}) or {}
    perf_dt = _parse_dt(stats.get("perf_start_time"))

    rows = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                rows.append(r)
    except Exception:
        return []

    entry_oids = {
        str(r.get("주문ID") or r.get("order_id") or "").strip()
        for r in rows
        if str(r.get("유형") or r.get("category") or "").strip() in ("진입", "*진입")
        and str(r.get("주문ID") or r.get("order_id") or "").strip()
    }

    grouped: Dict[Any, Dict[str, Any]] = {}
    seq = 0
    for r in rows:
        tstr = str(r.get("시간") or r.get("timestamp") or "").strip()
        dt = _parse_dt(tstr)
        if dt is None or (perf_dt and dt < perf_dt):
            continue
        cat = str(r.get("유형") or r.get("category") or "").strip()
        fee = abs(_safe_float(r.get("수수료(USDT)") or r.get("fee"), 0.0))
        if "청산" not in cat and cat.lower() != "close":
            continue
        pnl = _safe_float(r.get("수익(USDT)") or r.get("pnl"), 0.0)
        oid = str(r.get("주문ID") or r.get("order_id") or "").strip()
        if oid and oid in entry_oids and abs(pnl) <= 1e-12:
            continue
        sym = str(r.get("심볼") or r.get("symbol") or "").strip()
        side = str(r.get("방향") or r.get("side") or "").strip()
        px = _safe_float(r.get("가격") or r.get("price"), 0.0)
        amt = abs(_safe_float(r.get("수량") or r.get("amount"), 0.0))
        notional_est = px * amt if (px > 0 and amt > 0) else 0.0
        if oid:
            k: Any = (sym, oid)
        else:
            seq += 1
            k = (sym, f"__anon_{seq}_{tstr}")
        if k not in grouped:
            grouped[k] = {
                "ts": dt,
                "symbol": sym,
                "pnl": 0.0,
                "fee": 0.0,
                "notional": 0.0,
            }
        grouped[k]["pnl"] += pnl
        grouped[k]["fee"] += fee
        grouped[k]["notional"] += notional_est
        if dt > grouped[k]["ts"]:
            grouped[k]["ts"] = dt

    return sorted(grouped.values(), key=lambda x: x["ts"])


def check_cross_bot_portfolio_exposure(bots: List[int]) -> Dict[str, Any]:
    """[M16] Aggregate cross-bot gross/net exposure, same-symbol crowding, and 24h fleet drawdown."""
    alerts: List[Dict[str, str]] = []
    cache = _load_json(SENTINEL_CACHE_FILE, {}) or {}
    cbots = cache.get("bots") or {}
    now = time.time()

    total_equity = 0.0
    gross_notional = 0.0
    long_notional = 0.0
    short_notional = 0.0
    total_positions = 0
    sym_side_bots: Dict[str, List[str]] = {}

    for b in bots:
        bs = str(b)
        ent = cbots.get(bs)
        if not isinstance(ent, dict) or (now - _safe_float(ent.get("ts"), 0.0)) > 900:
            continue
        total_equity += _safe_float(ent.get("balance"), 0.0)
        for p in (ent.get("positions") or []):
            sym = str(p.get("symbol") or "")
            side = str(p.get("side") or "").lower()
            notional = abs(_safe_float(p.get("notional_usdt"), 0.0))
            if not sym or side not in ("long", "short"):
                continue
            total_positions += 1
            gross_notional += notional
            if side == "long":
                long_notional += notional
            else:
                short_notional += notional
            key = f"{sym}:{side}"
            sym_side_bots.setdefault(key, []).append(bs)

    net_notional = long_notional - short_notional
    bias_pct = round((abs(net_notional) / gross_notional) * 100.0, 1) if gross_notional > 0 else 0.0
    fleet_lev = round(gross_notional / total_equity, 2) if total_equity > 0 else 0.0

    # 1) Same symbol + direction crowding (QVT 동일전략 4봇 동시진입은 정상 → 5봇부터 WARN, 7봇부터 CRITICAL)
    crowded = {k: v for k, v in sym_side_bots.items() if len(v) >= 5}
    for key, bot_list in crowded.items():
        cnt = len(bot_list)
        if cnt >= 7:
            alerts.append({
                "bot_id": "8888",
                "key": f"portfolio_crowding_{key.replace('/', '_').replace(':', '_')}",
                "severity": "CRITICAL",
                "title": f"전 봇 동일종목 극심한 쏠림 ({key} × {cnt}봇)",
                "details": f"참여 봇: {', '.join(bot_list)} — 동반 손실 위험 높음",
                "recommendation": "신규 동방향 진입 자제 및 상관 리스크 점검 권고",
            })
        elif cnt >= 5:
            alerts.append({
                "bot_id": "8888",
                "key": f"portfolio_crowding_{key.replace('/', '_').replace(':', '_')}",
                "severity": "WARN",
                "title": f"전 봇 동일종목 집중 주의 ({key} × {cnt}봇)",
                "details": f"참여 봇: {', '.join(bot_list)}",
                "recommendation": "동일 종목·방향 과다 노출 여부 확인 권고",
            })

    # 2) Portfolio directional bias + aggregate leverage
    if total_positions >= 5 and bias_pct >= 85.0 and fleet_lev >= 2.5:
        direction = "LONG" if net_notional > 0 else "SHORT"
        alerts.append({
            "bot_id": "8888",
            "key": "portfolio_net_exposure",
            "severity": "CRITICAL",
            "title": f"전체 계좌 단방향 고레버리지 쏠림 ({direction} 편향 {bias_pct}%)",
            "details": f"포지션 {total_positions}건, Gross ${gross_notional:.2f} / Net ${net_notional:+.2f} (합산 레버리지 {fleet_lev:.2f}x)",
            "recommendation": "급반전 시 전 계좌 동반 드로다운 위험 — 비중 및 포지션 수 제한 점검 필요",
        })
    elif total_positions >= 5 and bias_pct >= 80.0 and fleet_lev >= 1.5:
        direction = "LONG" if net_notional > 0 else "SHORT"
        alerts.append({
            "bot_id": "8888",
            "key": "portfolio_net_exposure",
            "severity": "WARN",
            "title": f"전체 계좌 방향 편향 주의 ({direction} {bias_pct}%)",
            "details": f"포지션 {total_positions}건, Gross ${gross_notional:.2f} / Net ${net_notional:+.2f} (레버리지 {fleet_lev:.2f}x)",
            "recommendation": "포트폴리오 순노출 추이 관찰 권고",
        })

    # 3) 24h Fleet Equity Drop (snapshots.json)
    fleet_dd_24h_pct = None
    snaps = _load_json(SNAPSHOTS_FILE, []) or []
    if isinstance(snaps, list) and len(snaps) >= 2:
        now_dt = datetime.now()
        cutoff_24h = now_dt - timedelta(hours=24)
        ref_total = None
        for s in snaps:
            if not isinstance(s, dict):
                continue
            sdt = _parse_dt(s.get("timestamp") or s.get("ts") or "")
            if sdt and sdt >= cutoff_24h:
                bots_dict = s.get("bots") or {}
                if bots_dict:
                    ref_total = sum(_safe_float(bots_dict.get(str(b)), 0.0) for b in bots)
                    break
        cur_total = total_equity
        if cur_total <= 0 and isinstance(snaps[-1], dict):
            last_bots = snaps[-1].get("bots") or {}
            cur_total = sum(_safe_float(last_bots.get(str(b)), 0.0) for b in bots)
        if ref_total and ref_total > 0 and cur_total > 0:
            fleet_dd_24h_pct = round(((cur_total - ref_total) / ref_total) * 100.0, 2)
            if fleet_dd_24h_pct <= -10.0:
                alerts.append({
                    "bot_id": "8888",
                    "key": "portfolio_24h_drawdown",
                    "severity": "CRITICAL",
                    "title": f"전 봇 합산 자산 24h 급락 ({fleet_dd_24h_pct:+.2f}%)",
                    "details": f"24시간 전 ${ref_total:.2f} -> 현재 ${cur_total:.2f}",
                    "recommendation": "전체 포트폴리오 손실 속도 이상 — 원인 봇 분리 및 일시중단 승인 검토 필요",
                })
            elif fleet_dd_24h_pct <= -5.0:
                alerts.append({
                    "bot_id": "8888",
                    "key": "portfolio_24h_drawdown",
                    "severity": "WARN",
                    "title": f"전 봇 합산 자산 24h 하락 ({fleet_dd_24h_pct:+.2f}%)",
                    "details": f"24시간 전 ${ref_total:.2f} -> 현재 ${cur_total:.2f}",
                    "recommendation": "전체 계좌 손익 추이 모니터링 권고",
                })

    return {
        "alerts": alerts,
        "details": {
            "total_equity": round(total_equity, 2),
            "gross_notional": round(gross_notional, 2),
            "net_notional": round(net_notional, 2),
            "long_notional": round(long_notional, 2),
            "short_notional": round(short_notional, 2),
            "directional_bias_pct": bias_pct,
            "fleet_leverage": fleet_lev,
            "total_positions": total_positions,
            "crowded_symbol_sides": crowded,
            "fleet_24h_change_pct": fleet_dd_24h_pct,
        },
    }


def check_tca_execution_quality(bots: List[int]) -> Dict[str, Any]:
    """[M21] Compare realized execution fees vs strategy baseline cost_bps_rt & check stale orders/dust."""
    alerts: List[Dict[str, str]] = []
    baselines = (_load_json(BASELINES_FILE, {}) or {}).get("bots") or {}
    cache = _load_json(SENTINEL_CACHE_FILE, {}) or {}
    cbots = cache.get("bots") or {}
    per_bot: Dict[str, Any] = {}

    for b in bots:
        bs = str(b)
        bl = baselines.get(bs) or {}
        base_bps = _safe_float((bl.get("backtest") or {}).get("cost_bps_rt"), 10.0) or 10.0
        trades = _load_grouped_closed_trades(bs)[-20:]
        valid = [t for t in trades if t["notional"] > 0]
        cent = cbots.get(bs) or {}
        stale_oo = cent.get("stale_open_orders") or []
        dust_pos = cent.get("dust_positions") or []

        avg_exit_fee_bps = None
        if len(valid) >= 10:
            sum_not = sum(t["notional"] for t in valid)
            sum_fee = sum(t["fee"] for t in valid)
            if sum_not > 0:
                # trade_history close fee is one leg; multiply x2 to approximate round-trip bps vs cost_bps_rt
                avg_exit_fee_bps = round(((sum_fee / sum_not) * 10000.0) * 2.0, 2)
                if avg_exit_fee_bps >= base_bps * 3.0 and avg_exit_fee_bps >= 30.0:
                    alerts.append({
                        "bot_id": bs,
                        "key": "tca_fee_slippage_spike",
                        "severity": "WARN",
                        "title": f"실체결 왕복 수수료 급증 ({avg_exit_fee_bps:.1f}bps vs 기준 {base_bps:.0f}bps)",
                        "details": f"최근 {len(valid)}건 청산 추정 왕복 비용 {avg_exit_fee_bps:.1f}bps",
                        "recommendation": "테이커 비중 과다 또는 저가 코인 수수료 잠식 여부 점검 권고",
                    })

        per_bot[bs] = {
            "sample_n": len(valid),
            "est_rt_fee_bps": avg_exit_fee_bps,
            "baseline_cost_bps": base_bps,
            "stale_open_orders": len(stale_oo),
            "dust_positions": len(dust_pos),
        }

    return {"alerts": alerts, "details": per_bot}


def check_alpha_decay_and_market_regime(bots: List[int]) -> Dict[str, Any]:
    """[M22] Rolling 30-trade binomial win-rate Z-score & Profit Factor + BTC 1h volatility regime shock."""
    alerts: List[Dict[str, str]] = []
    baselines = (_load_json(BASELINES_FILE, {}) or {}).get("bots") or {}
    per_bot: Dict[str, Any] = {}

    for b in bots:
        bs = str(b)
        bl = baselines.get(bs) or {}
        bt = bl.get("backtest") or {}
        p0 = _safe_float(bt.get("win_rate_pct"), 50.0) / 100.0
        trades = _load_grouped_closed_trades(bs)[-30:]
        n = len(trades)
        if n < 25:
            per_bot[bs] = {"sample_n": n, "status": "insufficient_sample"}
            continue

        wins = sum(1 for t in trades if t["pnl"] > 0)
        gross_win = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (9.99 if gross_win > 0 else 1.0)
        wr = wins / n
        sd = math.sqrt(max(p0 * (1.0 - p0) / n, 1e-6))
        z_score = round((wr - p0) / sd, 2)
        exp_usdt = round(sum(t["pnl"] for t in trades) / n, 4)

        per_bot[bs] = {
            "sample_n": n,
            "win_rate_30_pct": round(wr * 100.0, 1),
            "baseline_win_rate_pct": round(p0 * 100.0, 1),
            "z_score": z_score,
            "profit_factor_30": pf,
            "expectancy_usdt": exp_usdt,
        }

        if z_score <= -2.6 and pf < 0.65:
            alerts.append({
                "bot_id": bs,
                "key": "alpha_decay_early",
                "severity": "CRITICAL",
                "title": f"조기 알파 감쇠 심각 (최근 {n}건 PF {pf:.2f}, Z={z_score:+.2f})",
                "details": f"실승률 {wr*100:.1f}% vs 백테스트 {p0*100:.1f}% (기대값 ${exp_usdt:+.4f}/건)",
                "recommendation": "레짐 드리프트 또는 전략 우위 상실 가능 — 보스 승인 후 파라미터/방향 점검 필요",
            })
        elif z_score <= -2.0 and pf < 0.85:
            alerts.append({
                "bot_id": bs,
                "key": "alpha_decay_early",
                "severity": "WARN",
                "title": f"조기 알파 감쇠 주의 (최근 {n}건 PF {pf:.2f}, Z={z_score:+.2f})",
                "details": f"실승률 {wr*100:.1f}% vs 백테스트 {p0*100:.1f}% (기대값 ${exp_usdt:+.4f}/건)",
                "recommendation": "추세/횡보 레짐 변화 및 최근 손익 추이 관찰 권고",
            })

    # BTC 48h volatility shock check
    btc_regime: Dict[str, Any] = {"ok": False}
    klines, err = http_get_json("https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=49", timeout=6.0)
    if isinstance(klines, list) and len(klines) >= 26:
        try:
            closes = [float(k[4]) for k in klines]
            rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]
            ret_4h = ((closes[-1] - closes[-5]) / closes[-5]) * 100.0 if len(closes) >= 5 else 0.0
            ret_24h = ((closes[-1] - closes[-25]) / closes[-25]) * 100.0 if len(closes) >= 25 else 0.0
            vol_48 = math.sqrt(sum(r * r for r in rets) / max(len(rets), 1))
            vol_6 = math.sqrt(sum(r * r for r in rets[-6:]) / max(len(rets[-6:]), 1))
            vol_ratio = round(vol_6 / vol_48, 2) if vol_48 > 0 else 1.0
            btc_regime = {
                "ok": True,
                "price": closes[-1],
                "ret_4h_pct": round(ret_4h, 2),
                "ret_24h_pct": round(ret_24h, 2),
                "vol_ratio_6h_vs_48h": vol_ratio,
            }
            if abs(ret_4h) >= 7.0 or abs(ret_24h) >= 12.0:
                alerts.append({
                    "bot_id": "8888",
                    "key": "market_regime_shock",
                    "severity": "CRITICAL",
                    "title": f"BTC 극단적 급변동 쇼크 (4h {ret_4h:+.2f}%, 24h {ret_24h:+.2f}%)",
                    "details": f"BTC=${closes[-1]:,.0f}, 변동성 배율 {vol_ratio:.2f}x",
                    "recommendation": "급변동 장세 중 슬리피지·연쇄청산·역추세 전략 리스크 주의",
                })
            elif abs(ret_4h) >= 4.0 or abs(ret_24h) >= 7.0 or vol_ratio >= 2.5:
                alerts.append({
                    "bot_id": "8888",
                    "key": "market_regime_shock",
                    "severity": "WARN",
                    "title": f"BTC 변동성 레짐 급변 주의 (4h {ret_4h:+.2f}%, 변동성 {vol_ratio:.2f}x)",
                    "details": f"BTC=${closes[-1]:,.0f}, 24h {ret_24h:+.2f}%",
                    "recommendation": "레짐 급변에 따른 손익 변동성 확대 관찰 권고",
                })
        except Exception as e:
            btc_regime = {"ok": False, "error": str(e)}
    elif err:
        btc_regime = {"ok": False, "error": err}

    return {"alerts": alerts, "details": {"per_bot_alpha": per_bot, "btc_regime": btc_regime}}


_ORDER_ACT_RE = re.compile(
    r"(\[ORDER\]|\[MAKER\].*(지정가 체결 완료|부분 체결|미체결.*취소|신호 폐기)|주문 실패|주문 취소 완료|개별 주문 취소 실패)",
    re.I,
)
_MAKER_FILL_RE = re.compile(r"\[MAKER\].*(지정가 체결 완료|부분 체결)", re.I)
_MAKER_MISS_RE = re.compile(r"\[MAKER\].*(미체결.*취소|신호 폐기)", re.I)


def _read_recent_log_lines(log_path: str, since_dt: datetime, max_bytes: int = 262144) -> List[str]:
    if not os.path.exists(log_path):
        return []
    out: List[str] = []
    try:
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            sz = f.tell()
            f.seek(max(0, sz - max_bytes))
            chunk = f.read().decode("utf-8", errors="ignore")
        for line in chunk.splitlines():
            if len(line) >= 19:
                try:
                    ldt = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                    if ldt < since_dt:
                        continue
                except ValueError:
                    pass
            out.append(line)
    except Exception:
        pass
    return out


def check_order_velocity_and_otr(bots: List[int]) -> Dict[str, Any]:
    """[M30 - MiFID II RTS 6] Detect runaway order loops & excessive Order-to-Trade Ratio in 15m."""
    alerts: List[Dict[str, str]] = []
    per_bot: Dict[str, Any] = {}
    now_dt = datetime.now()
    cutoff_15m = now_dt - timedelta(minutes=15)

    for b in bots:
        bs = str(b)
        bdir = os.path.join(BASE_PROJECT, bs)
        if not os.path.isdir(bdir) or os.path.exists(os.path.join(bdir, ".stopped")):
            continue
        lines = _read_recent_log_lines(os.path.join(bdir, "bot_engine.log"), cutoff_15m, max_bytes=196608)
        order_events = sum(1 for ln in lines if _ORDER_ACT_RE.search(ln))

        fills_15m = 0
        csv_path = os.path.join(bdir, "data", "trade_history.csv")
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
                    for r in list(csv.DictReader(f))[-80:]:
                        dt = _parse_dt(r.get("시간") or r.get("timestamp") or "")
                        if dt and dt >= cutoff_15m:
                            fills_15m += 1
            except Exception:
                pass

        otr = round(order_events / max(fills_15m, 1), 1)
        per_bot[bs] = {"order_events_15m": order_events, "fills_15m": fills_15m, "otr_15m": otr}

        if order_events >= 60 or (order_events >= 25 and otr >= 25.0):
            alerts.append({
                "bot_id": bs,
                "key": "otr_runaway_algo",
                "severity": "CRITICAL",
                "title": f"알고리즘 주문 폭주 의심 (15분 주문 {order_events}건, OTR {otr:.1f}:1)",
                "details": f"최근 15분 실제 주문/취소 {order_events}회 / 체결 {fills_15m}회",
                "recommendation": "무한 주문 루프 또는 RateLimit 위험 — 즉시 로그 확인 및 중단 검토 필요",
            })
        elif order_events >= 25 or (order_events >= 15 and otr >= 15.0):
            alerts.append({
                "bot_id": bs,
                "key": "otr_runaway_algo",
                "severity": "WARN",
                "title": f"주문 빈도·OTR 상승 주의 (15분 {order_events}건, OTR {otr:.1f}:1)",
                "details": f"최근 15분 주문/취소 {order_events}회 / 체결 {fills_15m}회",
                "recommendation": "메이커 반복 취소/재시도 여부 관찰 권고",
            })

    return {"alerts": alerts, "details": per_bot}


def check_maker_fill_ratio_and_adverse_selection(bots: List[int]) -> Dict[str, Any]:
    """[M31 - Live vs Backtest Parity] Track 24h maker fill ratio & quick (<5m) adverse selection losses."""
    alerts: List[Dict[str, str]] = []
    per_bot: Dict[str, Any] = {}
    now_dt = datetime.now()
    cutoff_24h = now_dt - timedelta(hours=24)

    for b in bots:
        bs = str(b)
        bdir = os.path.join(BASE_PROJECT, bs)
        if not os.path.isdir(bdir) or os.path.exists(os.path.join(bdir, ".stopped")):
            continue

        lines_24h = _read_recent_log_lines(os.path.join(bdir, "bot_engine.log"), cutoff_24h, max_bytes=1048576)
        fills = sum(1 for ln in lines_24h if _MAKER_FILL_RE.search(ln))
        misses = sum(1 for ln in lines_24h if _MAKER_MISS_RE.search(ln))
        attempts = fills + misses
        fill_ratio_pct = round((fills / attempts) * 100.0, 1) if attempts > 0 else None

        if attempts >= 8 and fill_ratio_pct is not None:
            if fill_ratio_pct < 15.0:
                alerts.append({
                    "bot_id": bs,
                    "key": "tca_maker_fill_low",
                    "severity": "CRITICAL",
                    "title": f"메이커 체결률 급락 ({fill_ratio_pct:.1f}%, {fills}/{attempts})",
                    "details": f"최근 24시간 지정가 시도 {attempts}회 중 {fills}회만 체결 (백테스트 패리티 이탈)",
                    "recommendation": "호가 오프셋·대기시간 조정 여부 점검 권고",
                })
            elif fill_ratio_pct < 30.0:
                alerts.append({
                    "bot_id": bs,
                    "key": "tca_maker_fill_low",
                    "severity": "WARN",
                    "title": f"메이커 체결률 저조 ({fill_ratio_pct:.1f}%, {fills}/{attempts})",
                    "details": f"최근 24시간 지정가 {attempts}회 중 {fills}회 체결",
                    "recommendation": "좋은 신호 미체결·역선택 추이 관찰 권고",
                })

        # Adverse selection: recent closed trades losing >=1% within <=300s from entry
        adv_rate_pct = None
        csv_path = os.path.join(bdir, "data", "trade_history.csv")
        if os.path.exists(csv_path):
            stats = _load_json(os.path.join(bdir, "data", "stats.json"), {}) or {}
            perf_dt = _parse_dt(stats.get("perf_start_time"))
            last_entry = {}
            pairs = []
            try:
                with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
                    for r in csv.DictReader(f):
                        dt = _parse_dt(r.get("시간") or r.get("timestamp") or "")
                        if not dt or (perf_dt and dt < perf_dt):
                            continue
                        sym = str(r.get("심볼") or r.get("symbol") or "").strip()
                        cat = str(r.get("유형") or r.get("category") or "").strip()
                        if cat in ("진입", "*진입"):
                            last_entry[sym] = dt
                        elif "청산" in cat and sym in last_entry:
                            dur = (dt - last_entry.pop(sym)).total_seconds()
                            pct = _safe_float(r.get("수익률(%)"), 0.0)
                            pairs.append((dur, pct))
            except Exception:
                pass
            recent_pairs = pairs[-20:]
            if len(recent_pairs) >= 15:
                adv_cnt = sum(1 for dur, pct in recent_pairs if 0 <= dur <= 300 and pct <= -1.0)
                adv_rate_pct = round((adv_cnt / len(recent_pairs)) * 100.0, 1)
                if adv_rate_pct >= 60.0:
                    alerts.append({
                        "bot_id": bs,
                        "key": "tca_adverse_selection",
                        "severity": "CRITICAL",
                        "title": f"체결 직후 역선택 손절 급증 ({adv_rate_pct:.0f}%)",
                        "details": f"최근 {len(recent_pairs)}건 중 {adv_cnt}건이 진입 5분 내 -1% 이상 손절",
                        "recommendation": "역선택(Adverse Selection) 우위 상실 의심 — 진입 필터 점검 필요",
                    })
                elif adv_rate_pct >= 40.0:
                    alerts.append({
                        "bot_id": bs,
                        "key": "tca_adverse_selection",
                        "severity": "WARN",
                        "title": f"체결 직후 단기 역행 비율 상승 ({adv_rate_pct:.0f}%)",
                        "details": f"최근 {len(recent_pairs)}건 중 {adv_cnt}건 5분 내 -1% 손절",
                        "recommendation": "단기 역행 패턴 관찰 권고",
                    })

        per_bot[bs] = {
            "maker_attempts_24h": attempts,
            "maker_fills_24h": fills,
            "maker_fill_ratio_pct": fill_ratio_pct,
            "adverse_selection_5m_pct": adv_rate_pct,
        }

    return {"alerts": alerts, "details": per_bot}


def compute_and_save_health_scorecard(
    bots: List[int],
    infra_summary: Optional[Dict[str, Any]] = None,
    portfolio_summary: Optional[Dict[str, Any]] = None,
    send_daily_briefing: bool = True,
) -> Dict[str, Any]:
    """[M26] Compute unified 0~100 fleet health score, save scorecard JSON, and send KST 08:00 briefing."""
    active_alerts = (load_proactive_alerts().get("active") or {})
    infra = infra_summary or _load_json(INFRA_HEALTH_FILE, {}) or {}
    hb_doc = (_load_json(HEARTBEAT_FILE, {}) or {}).get("heartbeats") or {}

    crit_cnt = sum(1 for v in active_alerts.values() if str((v or {}).get("severity")) == "CRITICAL")
    warn_cnt = sum(1 for v in active_alerts.values() if str((v or {}).get("severity")) == "WARN")

    # Domain deduction caps so single noisy domain doesn't mask everything
    process_score = 30
    protect_score = 25
    infra_score = 15
    portfolio_score = 15
    alpha_score = 15

    # Check heartbeats freshness (dead-man status)
    now = time.time()
    for role, limit in (("watchdog_entry", 300), ("watchdog_position", 180), ("watchdog_exit", 180), ("watchdog_profitability", 900)):
        ts = _safe_float((hb_doc.get(role) or {}).get("ts"), 0.0)
        if ts > 0 and (now - ts) > limit:
            process_score -= 6

    for k, v in active_alerts.items():
        sev = str((v or {}).get("severity") or "WARN").upper()
        if sev == "INFO":
            continue
        akey = str((v or {}).get("alert_key") or k)
        pts = 6 if sev == "CRITICAL" else 2
        if any(x in akey for x in (
            "unprotected", "liq", "protection", "orphan", "margin_mode",
            "auto_trading_off", "rapid_self_destruct", "engine_states_pollution",
            "sentinel_adl", "sentinel_basis", "sentinel_unauthorized", "sentinel_security",
        )):
            protect_score = max(0, protect_score - pts)
        elif any(x in akey for x in ("infra_", "host_", "feed_", "canary_", "security_")):
            infra_score = max(0, infra_score - pts)
        elif any(x in akey for x in ("portfolio_", "blackswan_")):
            portfolio_score = max(0, portfolio_score - pts)
        elif any(x in akey for x in ("alpha_", "tca_", "market_regime", "fee_ratio", "loss_streak", "peak_mdd", "config_gap", "otr_")):
            alpha_score = max(0, alpha_score - pts)
        else:
            process_score = max(0, process_score - pts)

    process_score = max(0, min(30, process_score))
    protect_score = max(0, min(25, protect_score))
    infra_score = max(0, min(15, infra_score))
    portfolio_score = max(0, min(15, portfolio_score))
    alpha_score = max(0, min(15, alpha_score))
    total_score = process_score + protect_score + infra_score + portfolio_score + alpha_score

    grade = "S (최적)" if total_score >= 92 else ("A (양호)" if total_score >= 80 else ("B (주의)" if total_score >= 65 else "C (경고)"))

    prev_sc = _load_json(SCORECARD_FILE, {}) or {}
    last_brief_date = str(prev_sc.get("last_briefing_date") or "")
    now_dt = datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")

    m16 = (portfolio_summary or {}).get("m16_exposure") or {}
    m18 = infra.get("m18_clock_latency_429") or {}
    m24 = infra.get("m24_host_resources") or {}

    briefed_now = False
    if send_daily_briefing and now_dt.hour == 8 and now_dt.minute < 20 and last_brief_date != today_str:
        okx_d = ((m18.get("venues") or {}).get("okx") or {})
        bnc_d = ((m18.get("venues") or {}).get("binance") or {})
        msg = (
            f"🛡️ **[8888 일일 워치독 건강 스코어카드 — {today_str} 08:00]**\n"
            f"• 종합 점수: **{total_score}/100 ({grade})**\n"
            f"• 세부 점수: 프로세스 {process_score}/30 · 보호/청산 {protect_score}/25 · 인프라 {infra_score}/15 · 포트폴리오 {portfolio_score}/15 · 알파/TCA {alpha_score}/15\n"
            f"• 활성 경보: CRITICAL {crit_cnt}건 / WARN {warn_cnt}건\n"
            f"• 합산 노출: 포지션 {m16.get('total_positions', 0)}건 · Gross ${m16.get('gross_notional', 0):.2f} · Net ${m16.get('net_notional', 0):+.2f} (레버리지 {m16.get('fleet_leverage', 0):.2f}x)\n"
            f"• 시계오차/디스크: OKX {okx_d.get('clock_drift_ms', '?')}ms · Binance {bnc_d.get('clock_drift_ms', '?')}ms · 디스크 {m24.get('disk_used_pct', '?')}%"
        )
        _send_discord(msg)
        _send_telegram(msg)
        last_brief_date = today_str
        briefed_now = True

    scorecard = {
        "updated": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "score": total_score,
        "grade": grade,
        "breakdown": {
            "process_and_sync_30": process_score,
            "protection_and_margin_25": protect_score,
            "infra_and_clock_15": infra_score,
            "portfolio_exposure_15": portfolio_score,
            "alpha_and_tca_15": alpha_score,
        },
        "active_critical": crit_cnt,
        "active_warn": warn_cnt,
        "last_briefing_date": last_brief_date,
        "briefed_now": briefed_now,
        "portfolio": portfolio_summary or {},
    }
    try:
        _atomic_write_json(SCORECARD_FILE, scorecard)
    except Exception:
        pass
    return scorecard


def run_portfolio_risk_audit(
    bots: List[int],
    infra_summary: Optional[Dict[str, Any]] = None,
    send_daily_briefing: bool = True,
) -> Dict[str, Any]:
    """Run M16/M21/M22/M30/M31 + M26 scorecard and return unified alerts & summary."""
    m16 = check_cross_bot_portfolio_exposure(bots)
    m21 = check_tca_execution_quality(bots)
    m22 = check_alpha_decay_and_market_regime(bots)
    m30 = check_order_velocity_and_otr(bots)
    m31 = check_maker_fill_ratio_and_adverse_selection(bots)
    all_alerts = m16["alerts"] + m21["alerts"] + m22["alerts"] + m30["alerts"] + m31["alerts"]
    summary = {
        "m16_exposure": m16["details"],
        "m21_tca": m21["details"],
        "m22_alpha_regime": m22["details"],
        "m30_otr": m30["details"],
        "m31_parity": m31["details"],
    }
    scorecard = compute_and_save_health_scorecard(
        bots,
        infra_summary=infra_summary,
        portfolio_summary=summary,
        send_daily_briefing=send_daily_briefing,
    )
    summary["scorecard"] = scorecard
    return {"alerts": all_alerts, "summary": summary, "scorecard": scorecard}
