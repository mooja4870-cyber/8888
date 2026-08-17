#!/usr/bin/env python3
"""verify_sl_scaling.py — 1시간봉은 손익절이 더 커야 하는가 (mooja 지적)

발견한 사실
──────────
같은 61종목·180일에서 재보니 변동성과 손절폭이 따로 논다.
  · 봉당 ATR      15m 0.533%  →  1h 1.176%   (2.21배)
  · 손절폭        15m 0.711%  →  1h 1.106%   (1.55배)
  · ATR 대비      15m 1.34×    →  1h 0.94×    ← **1h가 30% 좁다**

원인은 `core/strategy.py:235`의 하한·상한이 **두 TF 공용**이기 때문이다.
  하한 = max(ATR×0.8, 가격×0.6%)      DIV_MIN_SL_PCT
  상한 = 가격×2.0%, 넘으면 **신호 기각**  DIV_MAX_SL_PCT
1h ATR이 1.176%라 스윙 손절이 2%를 자주 넘고, 그러면 거래 기회 자체가 사라진다.
실제로 봉 수는 4배 차이인데 신호는 7.1배 차이다(3925 vs 551).

여기서 두 가지를 나눠 본다
  A. 손익절 크기를 배수로 키우면 나아지는가 (RR 유지 — 손절·익절 동시 확대)
  B. 상한 2%가 1h 신호를 얼마나 버리는가 (신호 재생성 필요 — 별도 스크립트)

이 스크립트는 A를 다룬다. 표본이 작은 1h는 격자가 흔들리므로 **표준오차를 함께
찍는다** — 차이가 오차 안이면 '좋아졌다'고 말하지 않는다.
"""
import json, sys
import numpy as np, pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_tf_exit_scaling import load, SIG15, SIG1H, FEE, MAX_POS


def run_trade(df, s, k_ch, hold, mult):
    """손절폭에 mult를 곱한다. 익절도 함께 커진다(RR 고정)."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(c)
    i, e, rr = s["i"], s["e"], s["rr"]
    risk = s["risk"] * mult
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
        ch = (peak - k_ch * a) if long else (peak + k_ch * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    last = c[min(j, end)]
    return min(j, end), ((last - e) / e if long else (e - last) / e) - FEE


def sim(frames, sigs, gates, lo, hi, k, hold, mult):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        if (gates[sym][i - 1] > 0) != (s["dir"] == "long"):
            continue
        ei, p = run_trade(frames[sym], s, k, hold, mult)
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def cell(p):
    if len(p) < 10:
        return f"{len(p)}건 표본부족"
    a = np.array(p) * 100
    m, se = a.mean(), a.std(ddof=1) / np.sqrt(len(a))
    return f"{a.sum():+6.1f}% (건당 {m:+.3f}±{se:.3f})"


def main():
    ema = lambda x, s: pd.Series(x).ewm(span=s, adjust=False).mean().values
    for tf, sigf, gate, k, hold, atr_now in (("15m", SIG15, 48, 4.0, 24, 1.34),
                                             ("1h", SIG1H, 12, 2.0, 24, 0.94)):
        frames = load(tf)
        n0 = len(next(iter(frames.values())))
        mid = n0 // 2
        sigs = json.load(open(sigf))
        gates = {s: np.where(d["close"].values > ema(d["close"].values, gate), 1, -1)
                 for s, d in frames.items()}
        print(f"\n{'═'*94}")
        print(f"  ■ {tf} — 현재 손절폭 {atr_now:.2f}×ATR · K={k} · 보유 {hold}봉")
        print(f"  {'손절 배수':<22}{'봉인 앞90일':>34}{'개발 뒤90일':>34}")
        print("  " + "─" * 92)
        for mult in (0.75, 1.0, 1.25, 1.5, 2.0):
            a = sim(frames, sigs, gates, 0, mid, k, hold, mult)
            b = sim(frames, sigs, gates, mid, n0, k, hold, mult)
            lab = f"×{mult:.2f} ({atr_now*mult:.2f}×ATR)"
            mark = "  ← 현행" if mult == 1.0 else ""
            print(f"  {lab:<22}{cell(a):>34}{cell(b):>34}{mark}")
        print("  " + "─" * 92)
        print("  ± 는 건당 손익의 표준오차. 차이가 오차 안이면 개선이라 부르지 않는다.")


if __name__ == "__main__":
    main()
