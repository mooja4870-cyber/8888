#!/usr/bin/env python3
"""sweep_4h_long.py — 4시간봉 3년 데이터로 추세 전략 재검증

왜
──
180일 검색에서 살아남은 건 4시간봉 추세 계열 3개뿐인데 표본이 76~169건이라
오차가 값만큼 컸다(+0.566±0.514). 48조합을 돌렸으니 우연히 2~3개가 양쪽
플러스로 나오는 건 정상이다. 표본을 늘리는 것 말고는 가릴 방법이 없다.

이번 자료: 88종목 × 6570봉(3년). 표본이 6배 이상 늘어 오차가 1/3로 준다.

**생존 편향 주의**: 3년 이력이 있는 종목만 남았다(434개 중 88개). 그 사이 상장
폐지된 종목은 빠져 있어 결과가 낙관 쪽으로 치우친다. 그래서 통과하더라도
곧바로 실거래에 올리지 않고, 최근 구간(6분할 마지막 두 칸)을 따로 본다.

판정
  · 앞 1.5년(봉인) / 뒤 1.5년(개발) 양쪽 건당 플러스
  · 6개월 6분할에서 **4칸 이상** 플러스 (한 구간이 전부를 만들면 가짜)
"""
import glob, json, os, sys
import numpy as np, pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_4h_3y"
FEE, SLIP, MAX_POS, WARM = 0.001, 0.0002, 3, 250
BARS_DAY = 6


def load():
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/okx_4h_*.json")):
        s = os.path.basename(p).replace("okx_4h_", "").replace(".json", "")
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        c, h, l = df["close"], df["high"], df["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=14, adjust=False).mean()
        out[s] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def sig_donchian(df, n):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    hh = pd.Series(h).rolling(n).max().shift(1).values
    ll = pd.Series(l).rolling(n).min().shift(1).values
    out = []
    for t in range(WARM, len(c) - 1):
        if not np.isfinite(hh[t]):
            continue
        if c[t] > hh[t]:
            out.append((t, "long"))
        elif c[t] < ll[t]:
            out.append((t, "short"))
    return out


def sig_double_bb(df, period=20, s_out=2.0, s_in=1.0):
    c = df["close"]
    m, sd = c.rolling(period).mean(), c.rolling(period).std()
    cv, mv, sv = c.values, m.values, sd.values
    out, armed = [], 0
    for t in range(WARM, len(cv) - 1):
        if not np.isfinite(sv[t]):
            continue
        if cv[t] < mv[t] - s_out * sv[t]:
            armed = -1
        elif cv[t] > mv[t] + s_out * sv[t]:
            armed = +1
        elif armed == -1 and cv[t] > mv[t] - s_in * sv[t]:
            out.append((t, "long")); armed = 0
        elif armed == +1 and cv[t] < mv[t] + s_in * sv[t]:
            out.append((t, "short")); armed = 0
    return out


def sig_xmom(frames, look, rebal, top):
    syms = list(frames)
    n = len(next(iter(frames.values())))
    closes = np.array([frames[s]["close"].values for s in syms])
    out = {s: [] for s in syms}
    for t in range(max(WARM, look), n - 1, rebal):
        base = closes[:, t - look]
        r = np.where(base > 0, (closes[:, t] - base) / np.where(base > 0, base, 1), np.nan)
        ok = np.where(np.isfinite(r))[0]
        if len(ok) < 2 * top:
            continue
        order = ok[np.argsort(r[ok])]
        for k in order[-top:]:
            out[syms[k]].append((t, "long"))
        for k in order[:top]:
            out[syms[k]].append((t, "short"))
    return out


def run_trade(df, t, direction, sl_mult, rr, k_ch, hold):
    o, h, l, c = (df["open"].values, df["high"].values,
                  df["low"].values, df["close"].values)
    atr = df["_atr"].values
    n = len(c)
    i = t + 1
    if i >= n:
        return i, None
    long = direction == "long"
    e = o[i] * (1 + SLIP) if long else o[i] * (1 - SLIP)
    a0 = atr[t]
    if not np.isfinite(a0) or a0 <= 0 or e <= 0:
        return i, None
    risk = sl_mult * a0 / e
    if risk <= 0 or risk > 0.25:
        return i, None
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak, end, j = e, min(n - 1, i + hold), i
    out = None
    while j <= end:
        gain = (h[j] - e) / e if long else (e - l[j]) / e
        if (long and l[j] <= sl) or (not long and h[j] >= sl):
            out = (sl - e) / e if long else (e - sl) / e
            break
        if gain >= tp_pct:
            out = tp_pct
            break
        peak = max(peak, h[j]) if long else min(peak, l[j])
        a = atr[j] if np.isfinite(atr[j]) else 0.0
        ch = (peak - k_ch * a) if long else (peak + k_ch * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if out is None:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), out - FEE - SLIP


def simulate(frames, sigmap, lo, hi, sl_mult, rr, k_ch, hold):
    allsig = sorted(((t, s, d) for s, v in sigmap.items() for t, d in v
                     if lo <= t < hi), key=lambda x: x[0])
    busy, openp, pnl = {}, [], []
    for t, sym, d in allsig:
        openp = [x for x in openp if x > t]
        if busy.get(sym, -1) >= t or len(openp) >= MAX_POS:
            continue
        ei, p = run_trade(frames[sym], t, d, sl_mult, rr, k_ch, hold)
        if p is None:
            continue
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def stat(p):
    if len(p) < 30:
        return None
    a = np.array(p) * 100
    return {"n": len(a), "sum": a.sum(), "mean": a.mean(),
            "se": a.std(ddof=1) / np.sqrt(len(a)), "win": 100 * (a > 0).mean()}


def fmt(s):
    if s is None:
        return "표본부족"
    return f"{s['n']:>5}건 승{s['win']:>2.0f}% {s['mean']:+.3f}±{s['se']:.3f}"


def main():
    frames = load()
    n0 = len(next(iter(frames.values())))
    mid = n0 // 2
    print(f"  {len(frames)}종목 · {n0}봉 = {n0/BARS_DAY/365:.1f}년 (4시간봉)")
    print(f"  생존 편향 주의: 3년 이력이 있는 종목만 (434개 중 {len(frames)}개)")

    strat = {}
    for n in (12, 30, 60):
        strat[f"돈치안{n}"] = {s: sig_donchian(d, n) for s, d in frames.items()}
    strat["이중볼린저"] = {s: sig_double_bb(d) for s, d in frames.items()}
    for look, rebal, top in ((30, 6, 8), (60, 12, 8), (120, 24, 8)):
        strat[f"모멘텀{look}"] = sig_xmom(frames, look, rebal, top)

    print("\n  " + "═" * 96)
    print(f"  {'전략':<12}{'손절':>6}{'RR':>5}{'K':>5}{'보유':>6}"
          f"{'봉인 앞1.5년':>26}{'개발 뒤1.5년':>26}{'6분할':>8}")
    print("  " + "─" * 96)
    keep = []
    q = n0 // 6
    for name, sm in strat.items():
        tot = sum(len(v) for v in sm.values())
        if tot < 200:
            continue
        for sl_mult in (1.5, 2.0, 3.0):
            for rr in (1.5, 2.5):
                for hold in (12, 30):
                    a = stat(simulate(frames, sm, 0, mid, sl_mult, rr, 4.0, hold))
                    b = stat(simulate(frames, sm, mid, n0, sl_mult, rr, 4.0, hold))
                    if not (a and b and a["mean"] > 0 and b["mean"] > 0):
                        continue
                    wins = 0
                    for k in range(6):
                        c = stat(simulate(frames, sm, k * q, (k + 1) * q,
                                          sl_mult, rr, 4.0, hold))
                        if c and c["mean"] > 0:
                            wins += 1
                    mark = "  ★채택후보" if wins >= 4 else ""
                    print(f"  {name:<12}{sl_mult:>6.1f}{rr:>5.1f}{4.0:>5.1f}{hold:>6}"
                          f"{fmt(a):>26}{fmt(b):>26}{wins:>6}/6{mark}", flush=True)
                    if wins >= 4:
                        keep.append((name, sl_mult, rr, hold, a, b, wins))
    print("  " + "─" * 96)
    print("\n  ■ 채택 후보 (양 구간 플러스 + 6분할 4칸 이상)")
    if not keep:
        print("    없음 — 전부 기각")
    else:
        for name, sm, rr, hold, a, b, w in sorted(keep, key=lambda x: -(x[4]["mean"] + x[5]["mean"])):
            print(f"    {name:<12} 손절ATR{sm:.1f} RR{rr:.1f} 보유{hold}봉  "
                  f"봉인 {a['mean']:+.3f}±{a['se']:.3f} / 개발 {b['mean']:+.3f}±{b['se']:.3f} · {w}/6")


if __name__ == "__main__":
    main()
