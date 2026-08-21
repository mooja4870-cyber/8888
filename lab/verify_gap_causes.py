#!/usr/bin/env python3
"""verify_gap_causes.py — 백테-실거래 괴리 −0.200%p는 어디서 오는가

괴리
────
실거래 건당 −0.147% vs 백테 +0.057%. 이 0.200%p가 100개 봇 미스터리의 핵심이다.
파라미터 조정으로 얻을 수 있는 건 다 합쳐 +0.017%p뿐이라(오늘 전수 검증),
괴리를 지우지 않으면 목표에 못 간다.

후보 넷
  1. 체결 미끄러짐 — 시장가라 호가를 먹고 들어간다
  2. 수수료        — 이미 실측(건당 0.101%)이고 백테도 0.1% 차감 중이라 중복 아님
  3. 봇이 백테와 다르게 동작 — 별도 확인 필요(로그 대조)
  4. **백테 자체가 낙관** ← 이 스크립트가 다루는 것

백테의 낙관 후보를 하나씩 켜서 얼마씩 깎이는지 잰다. 내가 통제할 수 있는 쪽이라
먼저 지워야 나머지가 좁혀진다.

  (가) 진입가 — 신호봉 **종가**에 산다고 가정했다. 실거래는 봉이 닫힌 뒤
       스캔이 돌아야 알고, 시장가로 들어간다. 다음 봉 **시가**가 현실적이다.
  (나) 미끄러짐 — 시장가 체결은 호가를 먹는다. 진입·청산 각 0.02~0.10%.
  (다) 봉 내부 순서 — 한 봉 안에서 고가·저가 순서를 모른다. 현재는 손절을
       먼저 보는 보수적 규칙이라 오히려 비관 쪽이다(참고용으로 반대도 잰다).
"""
import json, sys
import numpy as np, pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_tf_exit_scaling import load, SIG15, MAX_POS

K_CH, HOLD, GATE, FEE = 4.0, 24, 48, 0.001


def run_trade(df, s, entry_mode, slip, tp_first):
    h, l, c, o = (df["high"].values, df["low"].values,
                  df["close"].values, df["open"].values)
    atr = df["_atr"].values
    n = len(c)
    i, risk, rr = s["i"], s["risk"], s["rr"]
    long = s["dir"] == "long"

    # (가) 진입가
    if entry_mode == "close":          # 신호봉 종가 (현행 백테)
        e, start = s["e"], i
    else:                              # 다음 봉 시가 (현실적)
        if i >= n:
            return i, None
        e, start = o[i], i
    if e <= 0:
        return i, None
    # (나) 미끄러짐 — 불리한 쪽으로
    e = e * (1 + slip) if long else e * (1 - slip)

    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak, end, j = e, min(n - 1, start + HOLD), start
    out = None
    while j <= end:
        hit_sl = (long and l[j] <= sl) or (not long and h[j] >= sl)
        gain = (h[j] - e) / e if long else (e - l[j]) / e
        hit_tp = gain >= tp_pct
        # (다) 봉 내부 순서
        first_sl = hit_sl and not (tp_first and hit_tp)
        if first_sl:
            out = (sl - e) / e if long else (e - sl) / e
            break
        if hit_tp:
            out = tp_pct
            break
        peak = max(peak, h[j]) if long else min(peak, l[j])
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - K_CH * a) if long else (peak + K_CH * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if out is None:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), out - FEE - slip     # 청산 미끄러짐도 한 번 더


def sim(frames, sigs, gates, lo, hi, entry_mode="close", slip=0.0, tp_first=False):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        if (gates[sym][i - 1] > 0) != (s["dir"] == "long"):
            continue
        ei, p = run_trade(frames[sym], s, entry_mode, slip, tp_first)
        if p is None:
            continue
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def cell(p):
    if len(p) < 10:
        return f"{len(p)}건 표본부족"
    a = np.array(p) * 100
    return (f"{len(a):>3}건 {a.sum():+6.1f}% "
            f"(건당 {a.mean():+.3f}±{a.std(ddof=1)/np.sqrt(len(a)):.3f})")


def main():
    frames = load("15m")
    n0 = len(next(iter(frames.values())))
    mid = n0 // 2
    sigs = json.load(open(SIG15))
    ema = lambda x, s: pd.Series(x).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, GATE), 1, -1)
             for s, d in frames.items()}

    print("  8403 15분봉 · 61종목 180일 · 게이트 ON · K=4.0 · 보유 24봉")
    print("  목표: 실거래 건당 −0.147%를 백테가 재현하는가 (괴리 −0.200%p)")
    print("  " + "═" * 88)
    print(f"  {'가정':<34}{'봉인 앞90일':>27}{'개발 뒤90일':>27}")
    print("  " + "─" * 88)

    cases = [
        ("현행 백테 (종가 진입·무미끄러짐)", "close", 0.0000, False),
        ("진입만 다음봉 시가", "open", 0.0000, False),
        ("+ 미끄러짐 0.02%", "open", 0.0002, False),
        ("+ 미끄러짐 0.05%", "open", 0.0005, False),
        ("+ 미끄러짐 0.10%", "open", 0.0010, False),
        ("종가진입 + 미끄러짐 0.05%", "close", 0.0005, False),
        ("[참고] 봉내 TP 우선(낙관)", "close", 0.0000, True),
    ]
    base = None
    for nm, em, sl, tf in cases:
        a = sim(frames, sigs, gates, 0, mid, em, sl, tf)
        b = sim(frames, sigs, gates, mid, n0, em, sl, tf)
        pa = np.mean(a) * 100 if a else 0
        pb = np.mean(b) * 100 if b else 0
        if base is None:
            base = (pa, pb)
            mark = "  기준"
        else:
            mark = f"  건당 Δ{pa-base[0]:+.3f}/{pb-base[1]:+.3f}"
        print(f"  {nm:<34}{cell(a):>27}{cell(b):>27}{mark}")
    print("  " + "─" * 88)
    print("  실거래 건당 −0.147%에 가장 가까운 줄이 괴리의 정체다.")


if __name__ == "__main__":
    main()
