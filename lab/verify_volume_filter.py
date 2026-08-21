#!/usr/bin/env python3
"""verify_volume_filter.py — 거래대금 하한을 되돌리면 나아지는가

배경
────
8/11에 "신호가 안 나온다"는 이유로 `MIN_VOLUME_USDT`를 300만 → **50만**으로 낮추고
`SCAN_TOP_N`을 30 → 80으로 올렸다. 그 결과 소형 종목이 대거 들어왔고, 8403 실거래
65건 중 **80%가 $3M 미만 종목**이었으며 **손실의 86%**(−$2.78/−$3.23)가 거기서 났다.

당시엔 "표본이 부족하다"가 더 급해 보였다. 이제 표본은 확보됐으니 되돌릴 때
어떻게 되는지 본다. 거래 수가 줄어 총수익이 깎일 수도 있고, 나쁜 종목이 빠져
건당 손익이 오를 수도 있다. **둘 다 재야 판단할 수 있다.**

주의: 종목을 고르는 기준을 사후에 성과로 정하면 그건 곡선맞춤이다. 그래서
**성과가 아니라 거래대금**(사전에 알 수 있는 값)으로만 자른다.
"""
import glob, json, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_tf_exit_scaling import load, SIG15, FEE, MAX_POS

CACHE = "/Users/l/project/8888/lab_cache_live"
K_CH, HOLD, GATE = 4.0, 24, 48


def daily_quote_volume():
    """종목별 일 거래대금 중앙값(USDT). 15분봉 96개 = 1일."""
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/okx_15m_*.json")):
        s = os.path.basename(p).replace("okx_15m_", "").replace(".json", "")
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        q = (df["close"] * df["volume"]).rolling(96).sum()
        out[s] = float(q.dropna().median())
    return out


def run_trade(df, s):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(c)
    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = s["dir"] == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak, end, j = e, min(n - 1, i + HOLD), i
    while j <= end:
        gain = (h[j] - e) / e if long else (e - l[j]) / e
        if (long and l[j] <= sl) or (not long and h[j] >= sl):
            return j, ((sl - e) / e if long else (e - sl) / e) - FEE
        if gain >= tp_pct:
            return j, tp_pct - FEE
        peak = max(peak, h[j]) if long else min(peak, l[j])
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - K_CH * a) if long else (peak + K_CH * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    last = c[min(j, end)]
    return min(j, end), ((last - e) / e if long else (e - last) / e) - FEE


def sim(frames, sigs, gates, lo, hi, allowed):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi and sym in allowed), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        if (gates[sym][i - 1] > 0) != (s["dir"] == "long"):
            continue
        ei, p = run_trade(frames[sym], s)
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
    vol = daily_quote_volume()

    print(f"  8403 15분봉 · 61종목 180일 · 게이트 ON · K={K_CH} · 보유 {HOLD}봉")
    print(f"  일 거래대금 중앙값 분포: "
          f"최소 ${min(vol.values())/1e6:.2f}M · 중앙 ${np.median(list(vol.values()))/1e6:.1f}M "
          f"· 최대 ${max(vol.values())/1e6:.0f}M")
    print("  " + "═" * 84)
    print(f"  {'거래대금 하한':<18}{'종목':>6}{'봉인 앞90일':>30}{'개발 뒤90일':>30}")
    print("  " + "─" * 84)
    base = None
    for thr in (0, 1e6, 3e6, 10e6, 30e6, 100e6):
        allowed = {s for s, v in vol.items() if v >= thr}
        if len(allowed) < 3:
            continue
        a = sim(frames, sigs, gates, 0, mid, allowed)
        b = sim(frames, sigs, gates, mid, n0, allowed)
        ta, tb = sum(a) * 100, sum(b) * 100
        if base is None:
            base, mark = (ta, tb), "  ← 현행(50만)"
        else:
            d1, d2 = ta - base[0], tb - base[1]
            mark = "  ← 양쪽 개선" if (d1 > 0 and d2 > 0) else f"  (Δ{d1:+.0f}/{d2:+.0f})"
        lab = "없음(전체)" if thr == 0 else f"${thr/1e6:.0f}M"
        print(f"  {lab:<18}{len(allowed):>6}{cell(a):>30}{cell(b):>30}{mark}")
    print("  " + "─" * 84)

    # 거래대금 구간별로 나눠 보면 어디서 새는지 보인다
    print("\n  ── 거래대금 구간별 (겹치지 않게) ──")
    print(f"  {'구간':<18}{'종목':>6}{'봉인 앞90일':>30}{'개발 뒤90일':>30}")
    bands = [(0, 1e6), (1e6, 3e6), (3e6, 10e6), (10e6, 30e6), (30e6, 1e18)]
    for lo_v, hi_v in bands:
        allowed = {s for s, v in vol.items() if lo_v <= v < hi_v}
        if len(allowed) < 2:
            continue
        a = sim(frames, sigs, gates, 0, mid, allowed)
        b = sim(frames, sigs, gates, mid, n0, allowed)
        lab = (f"${lo_v/1e6:.0f}M~${hi_v/1e6:.0f}M" if hi_v < 1e17
               else f"${lo_v/1e6:.0f}M 이상")
        print(f"  {lab:<18}{len(allowed):>6}{cell(a):>30}{cell(b):>30}")


if __name__ == "__main__":
    main()
