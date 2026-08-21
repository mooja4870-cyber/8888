#!/usr/bin/env python3
"""
lab_v2.py — 시장 게이트 + 순수 트레일링 전략 검증 (180일, 역방향 봉인)

봉인 구간 설계
──────────────
1차 실험에서 05-12~08-10(90일)을 이미 개발·봉인으로 소진했다. 그 구간을 다시 봉인으로
쓰면 이미 본 데이터로 검증하는 셈이라 의미가 없다. 그래서 **시간을 거꾸로** 나눈다.

    개발  05-12 ~ 08-10 (90일)  ← 이미 들여다본 구간. 여기서만 만든다.
    봉인  02-11 ~ 05-12 (90일)  ← 한 번도 열지 않은 구간. 최종 1회만 사용.

1차 실험에서 얻은 두 가설을 검증한다.
  가설 A — 본전보호가 승리를 잘라낸다.
           실측(돈치안·개발): 본전보호 켜면 평균 승 +0.82%/손익비 0.21(−222%),
           끄면 평균 승 +9.18%/손익비 2.30(+305%).
  가설 B — 방향 게이트가 없으면 상승장에서 숏이 자해한다.
           실측(수축후돌파·07-11~08-10 폭등장): 롱 +8.01% / 숏 −49.28%.

따라서 이 전략은 **시장 추세와 같은 방향으로만** 진입하고, 청산은 손절과 트레일링만 쓴다.
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_180"
FEE = 0.001
BAR_MIN = 15
GATE_SYM = "BTC"          # 시장 방향 판정 기준 종목


def load():
    out = {}
    for p in sorted(glob.glob(os.path.join(CACHE, "binance_15m_*.json"))):
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        c, h, l = df["close"], df["high"], df["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        df["atr"] = tr.ewm(span=14, adjust=False).mean()
        df["atr_pct"] = df["atr"] / c
        out[os.path.basename(p).split("15m_")[1].split("_USDT")[0]] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def market_gate(frames, span=384):
    """시장 방향 게이트. 기준 종목이 장기 EMA 위면 +1(롱만), 아래면 −1(숏만)."""
    src = frames[GATE_SYM] if GATE_SYM in frames else next(iter(frames.values()))
    c = src["close"]
    ema = c.ewm(span=span, adjust=False).mean()
    return np.where(c.values > ema.values, 1, -1)


def signals(df, gate, lo, hi, p=96, sq=0.9, atr_sl=4.0, vol_mult=1.0):
    """변동성 수축 후 레인지 돌파. 단, 시장 게이트와 같은 방향만 채택한다."""
    c, h, l, v = (df[k].values for k in ("close", "high", "low", "volume"))
    ap = df["atr_pct"].values
    apm = pd.Series(ap).rolling(p * 3).mean().values
    hh = pd.Series(h).rolling(p).max().shift(1).values
    ll = pd.Series(l).rolling(p).min().shift(1).values
    vm = pd.Series(v).rolling(96).mean().shift(1).values
    out = []
    for i in range(max(p * 3 + 2, lo), hi):
        if not (apm[i] == apm[i]) or ap[i] <= 0 or apm[i] <= 0:
            continue
        if ap[i] > apm[i] * sq:                 # 수축 상태가 아니면 건너뜀
            continue
        if vol_mult > 0 and (not (vm[i] == vm[i]) or vm[i] <= 0 or v[i] < vm[i] * vol_mult):
            continue
        risk = ap[i] * atr_sl
        if gate[i] > 0 and c[i] > hh[i]:
            out.append((i, "long", risk))
        elif gate[i] < 0 and c[i] < ll[i]:
            out.append((i, "short", risk))
    return out


def simulate(sigs, df, hold=288, kch=4.0):
    """손절 + 샹들리에 트레일링만. 본전보호·분할익절 없음(가설 A)."""
    h, l, c, atr = (df[k].values for k in ("high", "low", "close", "atr"))
    n = len(df)
    res, busy = [], -1
    for i, d, risk in sigs:
        if i <= busy or risk <= 0:
            continue
        e = c[i]
        long = d == "long"
        sl = e * (1 - risk) if long else e * (1 + risk)
        peak = e
        end = min(n - 1, i + hold)
        j, done, out = i + 1, False, 0.0
        while j <= end:
            hi, lo = h[j], l[j]
            peak = max(peak, hi) if long else min(peak, lo)
            a = atr[j] if atr[j] == atr[j] else 0.0
            ch = peak - kch * a if long else peak + kch * a
            sl = max(sl, ch) if long else min(sl, ch)
            if (long and lo <= sl) or (not long and hi >= sl):
                out = (sl - e) / e if long else (e - sl) / e
                done = True
                break
            j += 1
        if not done:
            last = c[min(j, end)]
            out = (last - e) / e if long else (e - last) / e
        res.append(out)
        busy = min(j, end)
    return res


def score(res, days):
    if not res:
        return dict(n=0, wr=0.0, net=0.0, mo=0.0)
    net = sum(res) - FEE * len(res)
    return dict(n=len(res), wr=100.0 * sum(1 for x in res if x > 0) / len(res),
                net=net * 100, mo=net * 100 * 30 / days)


def run(frames, gates, lo_r, hi_r, days, nseg=3, **kw):
    tot, segs = [], [[] for _ in range(nseg)]
    for sym, df in frames.items():
        n = len(df)
        lo, hi = int(n * lo_r), int(n * hi_r)
        sg = signals(df, gates[sym], lo, hi, **{k: v for k, v in kw.items()
                                                if k in ("p", "sq", "atr_sl", "vol_mult")})
        tot += simulate(sg, df, kw.get("hold", 288), kw.get("kch", 4.0))
        step = (hi - lo) // nseg
        for k in range(nseg):
            s2 = [s for s in sg if lo + k * step <= s[0] < lo + (k + 1) * step]
            segs[k] += simulate(s2, df, kw.get("hold", 288), kw.get("kch", 4.0))
    return score(tot, days), [score(s, days / nseg) for s in segs]


def main():
    frames = load()
    n0 = len(next(iter(frames.values())))
    g = market_gate(frames)
    gates = {s: g for s in frames}          # 시장 게이트는 전 종목 공통
    half = 0.5
    print(f"  {len(frames)}종목 · {n0}봉 = {n0*BAR_MIN/60/24:.0f}일")
    print(f"  개발 = 뒤 90일(05-12~08-10, 이미 탐색) · 봉인 = 앞 90일(02-11~05-12, 미개봉)")
    print("  " + "═" * 74)
    print(f"  {'설정':<26}{'건수':>6}{'승률':>7}{'순손익':>10}{'월환산':>9}   3분할")
    print("  " + "─" * 74)
    variants = [
        ("기준(수축0.9·게이트)",   dict(sq=0.9, vol_mult=0.0)),
        ("+ 거래량 1.2배",         dict(sq=0.9, vol_mult=1.2)),
        ("수축 0.7",               dict(sq=0.7, vol_mult=0.0)),
        ("손절 ATRx3",             dict(sq=0.9, vol_mult=0.0, atr_sl=3.0)),
        ("트레일 K=6",             dict(sq=0.9, vol_mult=0.0, kch=6.0)),
    ]
    ok_list = []
    for nm, kw in variants:
        o, ss = run(frames, gates, half, 1.0, 90.0, **kw)
        mark = " ".join("+" if s["net"] > 0 else "-" for s in ss)
        good = o["net"] > 0 and all(s["net"] > 0 for s in ss)
        print(f"  {nm:<26}{o['n']:>6}{o['wr']:>6.0f}%{o['net']:>+9.2f}%{o['mo']:>+8.1f}%   {mark} {'✅' if good else ''}")
        if good:
            ok_list.append((nm, kw))
    print("  " + "─" * 74)
    print(f"  개발 통과: {[x[0] for x in ok_list] or '없음'}")
    if ok_list:
        print("\n  ■ 봉인 구간 개봉 (앞 90일, 최초 1회)")
        print("  " + "─" * 74)
        for nm, kw in ok_list:
            o, _ = run(frames, gates, 0.0, half, 90.0, nseg=1, **kw)
            v = "🟢 통과" if o["net"] > 0 else "🔴 탈락"
            print(f"  {nm:<26}{o['n']:>6}{o['wr']:>6.0f}%{o['net']:>+9.2f}%{o['mo']:>+8.1f}%   {v}")


if __name__ == "__main__":
    main()
