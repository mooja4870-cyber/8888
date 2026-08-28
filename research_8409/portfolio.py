"""
포트폴리오 단위 시뮬레이터 — MAX_POSITIONS 제한을 반영한다.

종목별로 따로 돌리면 '모든 종목을 동시에 보유할 수 있다'고 가정하게 된다.
실제 봇은 MAX_POSITIONS(기본 3)로 동시 보유가 묶여 있어, 보유기간이 긴 전략일수록
잡지 못하는 신호가 늘어난다. 이 차이를 무시하면 백테스트가 실현 불가능한
수익을 만들어낸다.

규칙
  · 봉을 시간순으로 함께 진행한다(종목 간 시각 정렬).
  · 빈 슬롯이 있을 때만 진입한다. 같은 봉에 여러 신호가 겹치면 심볼명 순으로 채운다
    (신호 강도로 고르면 그 자체가 또 하나의 최적화 자유도가 된다).
  · 청산 판정은 종목별 시뮬레이터와 동일: SL 우선 → TP → 보유상한.
"""
import numpy as np
import pandas as pd

FEE_TAKER = 0.0005


def simulate_portfolio(data, sig, max_hold_bars, max_positions=3,
                       notional=7.0, entry_fee=FEE_TAKER, exit_fee=FEE_TAKER,
                       sl_atr=2.0, tp_atr=4.0):
    """data: {symbol: df(timestamp,open,high,low,close,volume)}"""
    syms = sorted(data)
    # 공통 시간축으로 정렬 — 종목마다 봉 수가 달라도 시각으로 맞춘다
    idx = sorted(set().union(*[set(df["timestamp"]) for df in data.values()]))
    pos_of = {s: {t: i for i, t in enumerate(data[s]["timestamp"])} for s in syms}

    arr = {}
    for s in syms:
        df = data[s]
        arr[s] = {k: df[k].values.astype(float) for k in ("open", "high", "low", "close")}

    open_pos = {}          # symbol -> dict
    trades = []

    for t in idx:
        # ── 1) 청산 먼저 (슬롯을 비워야 같은 봉에서 신규가 들어올 수 있다)
        for s in list(open_pos):
            i = pos_of[s].get(t)
            if i is None:
                continue
            p = open_pos[s]
            held = i - p["i"]
            hi, lo, cl = arr[s]["high"][i], arr[s]["low"][i], arr[s]["close"][i]
            px, kind = None, None
            if p["dir"] == "long":
                if lo <= p["sl"]:
                    px, kind = p["sl"], "SL"
                elif hi >= p["tp"]:
                    px, kind = p["tp"], "TP"
            else:
                if hi >= p["sl"]:
                    px, kind = p["sl"], "SL"
                elif lo <= p["tp"]:
                    px, kind = p["tp"], "TP"
            if px is None and held >= max_hold_bars:
                px, kind = cl, "MAXHOLD"
            if px is not None:
                r = (px / p["px"] - 1) * (1 if p["dir"] == "long" else -1)
                gross = notional * r
                fee = notional * (entry_fee + exit_fee)
                trades.append({"symbol": s, "t": t, "kind": kind, "ret": r,
                               "gross": gross, "fee": fee, "net": gross - fee})
                del open_pos[s]

        # ── 2) 신규 진입 (빈 슬롯만큼)
        if len(open_pos) >= max_positions:
            continue
        for s in syms:
            if len(open_pos) >= max_positions:
                break
            if s in open_pos:
                continue
            i = pos_of[s].get(t)
            if i is None or i < 60 or i + 1 >= len(arr[s]["open"]):
                continue
            sg = sig.at(data[s], i)
            if sg is None or sg.direction == "none" or sg.atr <= 0:
                continue
            entry = arr[s]["open"][i + 1]          # 다음 봉 시가 (look-ahead 차단)
            if sg.direction == "long":
                sl, tp = entry - sg.atr * sl_atr, entry + sg.atr * tp_atr
            else:
                sl, tp = entry + sg.atr * sl_atr, entry - sg.atr * tp_atr
            open_pos[s] = {"i": i, "px": entry, "dir": sg.direction, "sl": sl, "tp": tp}

    return trades


def report(trades, data, nsplit=4):
    if not trades:
        return None
    ts = sorted(set().union(*[set(df["timestamp"]) for df in data.values()]))
    bounds = [ts[len(ts) * k // nsplit] for k in range(nsplit)] + [ts[-1]]
    parts = []
    for k in range(nsplit):
        lo, hi = bounds[k], bounds[k + 1]
        parts.append(sum(x["net"] for x in trades if lo <= x["t"] < hi))
    bysym = {}
    for x in trades:
        bysym[x["symbol"]] = bysym.get(x["symbol"], 0.0) + x["net"]
    g = sum(x["gross"] for x in trades)
    return {
        "n": len(trades), "gross": g, "net": sum(x["net"] for x in trades),
        "parts": parts, "bysym": bysym,
        "pos": sum(1 for v in bysym.values() if v > 0), "nsym": len(bysym),
        "edge_bp": 10000 * g / (len(trades) * 7.0),
        "all_pos": all(p > 0 for p in parts),
    }
