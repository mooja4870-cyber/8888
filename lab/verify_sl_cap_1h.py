#!/usr/bin/env python3
"""verify_sl_cap_1h.py — 손절 상한 2%가 1시간봉 신호를 버리고 있는가

경위
────
mooja 지적: "1시간봉 봇은 손익절 크기도 좀 더 커야 하는 것 아니냐."
재보니 사실이었다 — ATR 대비 손절폭이 15m 1.34×, 1h 0.94×로 1h가 30% 좁다.

그런데 손절폭을 배수로 키우는 시험(`verify_sl_scaling.py`)은 방향만 맞고
차이가 표준오차 안이었다(0.5~0.9σ). 표본이 551건뿐이라 가릴 수가 없다.

**그 표본 부족 자체가 같은 원인일 수 있다.** `core/strategy.py:237`:
    if swing_risk <= 0 or risk / c_close > DIV_MAX_SL_PCT:   # 0.02
        → 신호 기각
1h ATR이 1.176%라 정상적인 스윙 손절이 2%를 자주 넘고, 그러면 **거래 기회 자체가
사라진다**. 실제로 봉 수는 4배 차이인데 신호는 7.1배 차이다(3925 vs 551).

즉 상한을 올리면 (가) 버려지던 신호가 살아나 표본이 늘고 (나) 손절폭이 ATR에
맞게 넓어진다. 두 효과를 한 번에 본다.

상한을 바꾸면 신호가 달라지므로 **재생성이 필요하다**(캐시 재사용 불가).
"""
import json, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_tf_exit_scaling import load, FEE, MAX_POS, WARMUP

BOT = "/Users/l/project/8403"
OUT = "/Users/l/project/8888/lab/_sigcache_1h_cap{}.json"
CAPS = (0.02, 0.03, 0.04, 0.06)      # 현행 2% · 3% · 4% · 6%


def gen(frames, cap):
    path = OUT.format(int(cap * 100))
    if os.path.exists(path):
        d = json.load(open(path))
        if set(d) == set(frames):
            print(f"    캐시 재사용 (상한 {cap*100:.0f}%)", flush=True)
            return d
    cwd = os.getcwd()
    sys.path.insert(0, BOT)
    os.chdir(BOT)
    from core.strategy import StrategyEngine
    st = StrategyEngine()
    st.cfg.DIV_MAX_SL_PCT = cap          # 상한만 바꾼다
    out = {}
    for n, (s, df) in enumerate(frames.items(), 1):
        sg = []
        for i in range(WARMUP, len(df) - 1):
            g = st.generate_signal(df.iloc[i - WARMUP:i], s)
            if g.direction == "none":
                continue
            e, sl, tp = g.close, g.swing_sl_price, g.tp1_price
            if not (e > 0 and sl > 0 and tp > 0):
                continue
            risk = abs(e - sl) / e
            if risk <= 0:
                continue
            sg.append({"i": i, "dir": g.direction, "e": e, "risk": risk,
                       "rr": abs(tp - e) / e / risk})
        out[s] = sg
        if n % 20 == 0:
            print(f"      [{n}/{len(frames)}] 누적 {sum(len(v) for v in out.values())}건", flush=True)
    os.chdir(cwd)
    json.dump(out, open(path, "w"))
    return out


def run_trade(df, s, k, hold):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(c)
    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = s["dir"] == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak, end, j = e, min(n - 1, i + hold), i
    while j <= end:
        gain = (h[j] - e) / e if long else (e - l[j]) / e
        if (long and l[j] <= sl) or (not long and h[j] >= sl):
            return j, ((sl - e) / e if long else (e - sl) / e) - FEE
        if gain >= tp_pct:
            return j, tp_pct - FEE
        peak = max(peak, h[j]) if long else min(peak, l[j])
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k * a) if long else (peak + k * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    last = c[min(j, end)]
    return min(j, end), ((last - e) / e if long else (e - last) / e) - FEE


def sim(frames, sigs, gates, lo, hi, k=2.0, hold=24):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        if (gates[sym][i - 1] > 0) != (s["dir"] == "long"):
            continue
        ei, p = run_trade(frames[sym], s, k, hold)
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def cell(p):
    if len(p) < 10:
        return f"{len(p)}건 표본부족"
    a = np.array(p) * 100
    return f"{len(a):>3}건 {a.sum():+6.1f}% (건당 {a.mean():+.3f}±{a.std(ddof=1)/np.sqrt(len(a)):.3f})"


def main():
    frames = load("1h")
    n0 = len(next(iter(frames.values())))
    mid = n0 // 2
    ema = lambda x, s: pd.Series(x).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 12), 1, -1)
             for s, d in frames.items()}
    print(f"  1시간봉 {len(frames)}종목 · {n0}봉 = 180일 · K=2.0 · 보유 24봉")
    print(f"  참고: 15분봉은 같은 기간 신호 3925건 (봉 수는 4배 차이)")
    print("  " + "═" * 88)
    print(f"  {'손절 상한':<14}{'신호':>8}{'손절폭 중앙':>12}{'봉인 앞90일':>32}{'개발 뒤90일':>32}")
    print("  " + "─" * 88)
    for cap in CAPS:
        sigs = gen(frames, cap)
        nsig = sum(len(v) for v in sigs.values())
        risks = [x["risk"] * 100 for v in sigs.values() for x in v]
        med = np.median(risks) if risks else 0
        a = sim(frames, sigs, gates, 0, mid)
        b = sim(frames, sigs, gates, mid, n0)
        mark = "  ← 현행" if abs(cap - 0.02) < 1e-9 else ""
        print(f"  {cap*100:>5.0f}%{'':<8}{nsig:>8}{med:>11.2f}%{cell(a):>32}{cell(b):>32}{mark}")
    print("  " + "─" * 88)
    print("  ± 는 건당 손익의 표준오차. 차이가 오차 안이면 개선이라 부르지 않는다.")


if __name__ == "__main__":
    main()
