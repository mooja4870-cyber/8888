#!/usr/bin/env python3
"""verify_regime_longonly.py — 롱 전용 5봇이 하락장에서 버티는가

mooja 질문
─────────
5봇 모두 롱 전용이다. 지금은 상승장이라 괜찮아 보이지만, 하락장이 오면
① 진입 기회가 줄고 ② 수익성도 나빠지지 않는가.

우려에 근거가 있다. 세력흔적 신호 수식은 **"15봉 신고가 돌파 + 양봉 + 거래량 급증"**
이라, 하락장에는 신고가가 드물어 **구조적으로 신호가 줄어든다.**

그런데 반대 방향 실측도 있다.
  · 세력흔적 검증: 봉인(하락) −0.239% vs 개발(상승) −0.097% → **하락 구간이 더 나빴다**
  · 200일선 검정: 알트코인은 **우상향 구간의 +60일 수익이 −16.92%**로 우하향(−5.04%)보다 나빴다
크립토는 주식 지수와 다르게 움직이므로 직접 재야 한다.

무엇을 재나
  ① 국면 정의 — BTC 200일선 위/아래 × 기울기로 상승·횡보·하락 구분
  ② 진입 기회 — 국면별 신호 건수 (하락장에 몇 % 줄어드는가)
  ③ 수익성   — 국면별 건당 손익·승률
  ④ 대안 비교 — 롱 전용 / 롱+숏 / 하락장 거래중단

자료: 194종목 · 최대 3년 · 일봉(4시간봉 6개 합산). 진입은 다음 봉 시가.
"""
import sys
import numpy as np, pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_ma_expanded import load_daily_aligned, run_trade, MAX_POS

N_BREAK, N_VOL = 15, 20
MA_REG, SLOPE_N = 200, 20


def btc_regime(frames, n):
    """BTC 기준 국면. +1 상승 / 0 횡보 / −1 하락.
    200일선 위 + 기울기 상승 = 상승 / 아래 + 기울기 하락 = 하락 / 나머지 횡보."""
    btc = frames.get("BTC")
    if btc is None:
        return np.zeros(n)
    c = btc["close"]
    m = c.rolling(MA_REG).mean().values
    cv = c.values
    r = np.zeros(n)
    for t in range(MA_REG + SLOPE_N, n):
        if not (np.isfinite(m[t]) and np.isfinite(m[t - SLOPE_N]) and np.isfinite(cv[t])):
            continue
        above = cv[t] > m[t]
        rising = m[t] > m[t - SLOPE_N]
        r[t] = 1 if (above and rising) else (-1 if (not above and not rising) else 0)
    return r


def sniper_signals(df):
    """세력흔적 신호 수식 X1~X5 (롱). 방향 반전용으로 숏 조건도 함께 낸다."""
    c, o, h, l, v = (df["close"].values, df["open"].values, df["high"].values,
                     df["low"].values, df["volume"].values)
    cs = pd.Series(c)
    hi_c = cs.rolling(N_BREAK).max().shift(1).values
    hi_c_p = cs.rolling(N_BREAK).max().shift(2).values
    lo_c = cs.rolling(N_BREAK).min().shift(1).values
    lo_c_p = cs.rolling(N_BREAK).min().shift(2).values
    hi_h = pd.Series(h).rolling(N_BREAK).max().shift(1).values
    lo_l = pd.Series(l).rolling(N_BREAK).min().shift(1).values
    vema = pd.Series(v).ewm(span=N_VOL, adjust=False).mean().values
    okv = df["_ok"].values
    out = []
    for t in range(N_BREAK + N_VOL + 2, len(c) - 1):
        if not okv[t] or not np.isfinite(hi_c[t]) or not np.isfinite(vema[t]):
            continue
        mid = (hi_h[t] + lo_l[t]) / 2.0
        if (c[t] > hi_c[t] and c[t - 1] < hi_c_p[t] and c[t] > o[t]
                and v[t] > vema[t] and c[t] > mid):
            out.append((t, "long"))
        elif (c[t] < lo_c[t] and c[t - 1] > lo_c_p[t] and c[t] < o[t]
                and v[t] > vema[t] and c[t] < mid):
            out.append((t, "short"))      # 대칭 조건 (하락 신고저 이탈)
    return out


def sim(frames, sigmap, reg, want_reg, mode, sl_atr=3.0, hold=20):
    """mode: 'long' 롱전용 / 'both' 롱숏 / 'halt' 하락장 거래중단."""
    allsig = sorted(((t, s, d) for s, v in sigmap.items() for t, d in v),
                    key=lambda x: x[0])
    busy, openp, pnl = {}, [], []
    for t, sym, d in allsig:
        if want_reg is not None and reg[t] != want_reg:
            continue
        if mode == "long" and d != "long":
            continue
        if mode == "halt" and (reg[t] < 0 or d != "long"):
            continue
        openp = [x for x in openp if x > t]
        if busy.get(sym, -1) >= t or len(openp) >= MAX_POS:
            continue
        ei, p = run_trade(frames[sym], t, d, sl_atr, hold)
        if p is None:
            continue
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def stat(pnl):
    """verify_ma_expanded.stat은 (t,ei,p) 튜플을 받는다. 여기선 손익 배열이라 따로 둔다."""
    import math
    if len(pnl) < 5:
        return None
    a = np.array(pnl) * 100
    se = a.std(ddof=1) / math.sqrt(len(a))
    return {"n": len(a), "mean": a.mean(), "win": 100 * (a > 0).mean(),
            "se": se, "sigma": a.mean() / se if se > 0 else 0}


def f_(s):
    return "표본부족" if s is None else \
        f"{s['n']:>4}건 승{s['win']:>2.0f}% {s['mean']:+.3f}±{s['se']:.3f}({s['sigma']:+.1f}σ)"


def main():
    frames, N = load_daily_aligned()
    reg = btc_regime(frames, N)
    print(f"  {len(frames)}종목 · {N}일 · BTC {MA_REG}일선 기준 국면")

    days = {1: int((reg == 1).sum()), 0: int((reg == 0).sum()), -1: int((reg == -1).sum())}
    tot = sum(days.values())
    print(f"\n  ■ 국면 분포")
    for k, nm in ((1, "상승"), (0, "횡보"), (-1, "하락")):
        print(f"    {nm}: {days[k]:>5}일 ({100*days[k]/tot:>4.1f}%)")

    print("\n  신호 계산 중...", flush=True)
    sig = {s: sniper_signals(d) for s, d in frames.items()}
    allsig = [(t, s, d) for s, v in sig.items() for t, d in v]
    print(f"  전체 신호 {len(allsig)}건 (롱 {sum(1 for x in allsig if x[2]=='long')} / "
          f"숏 {sum(1 for x in allsig if x[2]=='short')})")

    print(f"\n  ■ ② 진입 기회 — 국면별 롱 신호 (하루당)")
    print(f"    {'국면':<8}{'일수':>7}{'롱신호':>9}{'하루당':>9}{'숏신호':>9}{'하루당':>9}")
    base = None
    for k, nm in ((1, "상승"), (0, "횡보"), (-1, "하락")):
        L = sum(1 for t, s, d in allsig if reg[t] == k and d == "long")
        S = sum(1 for t, s, d in allsig if reg[t] == k and d == "short")
        dd = max(days[k], 1)
        if k == 1:
            base = L / dd
        print(f"    {nm:<8}{days[k]:>7}{L:>9}{L/dd:>9.1f}{S:>9}{S/dd:>9.1f}")
    print(f"    → 상승장 대비 하락장 롱 신호 비율: "
          f"{(sum(1 for t,s,d in allsig if reg[t]==-1 and d=='long')/max(days[-1],1))/base*100:.0f}%")

    print(f"\n  ■ ③ 국면별 수익성 (롱 전용)")
    print(f"    {'국면':<8}{'결과':>40}")
    for k, nm in ((1, "상승"), (0, "횡보"), (-1, "하락")):
        print(f"    {nm:<8}{f_(stat(sim(frames, sig, reg, k, 'long'))):>40}")

    print(f"\n  ■ ④ 대안 비교 (하락 국면만)")
    print(f"    {'방식':<16}{'결과':>40}")
    for mode, nm in (("long", "롱 전용(현행)"), ("both", "롱+숏 허용")):
        print(f"    {nm:<16}{f_(stat(sim(frames, sig, reg, -1, mode))):>40}")
    print(f"    {'하락장 중단':<16}{'거래 0건 (손실 0)':>40}")

    print(f"\n  ■ 전 구간 종합")
    print(f"    {'방식':<16}{'결과':>40}")
    for mode, nm in (("long", "롱 전용(현행)"), ("both", "롱+숏 허용"), ("halt", "하락장 중단")):
        print(f"    {nm:<16}{f_(stat(sim(frames, sig, reg, None, mode))):>40}")


if __name__ == "__main__":
    main()
