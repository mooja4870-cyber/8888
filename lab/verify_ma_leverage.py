#!/usr/bin/env python3
"""verify_ma_leverage.py — MA20/100으로 월 7~11%에 닿을 수 있는가

mooja의 목적
───────────
월 **7~11%**. 지금까지 우리가 검증한 최고는 8403 MA20/100의 **월 +3.7%**(1.7σ)였다.
모자란 만큼을 **보유기간**과 **레버리지**로 메울 수 있는지, 그 대가로 낙폭이
얼마나 커지는지를 숫자로 낸다.

왜 이 전략인가
────────────
264조합 중 **유일하게 최종확인을 통과**했다. 그리고 문헌이 독립적으로 지지한다
(Han·Kang·Ryu: 시계열 모멘텀은 비용을 넣어도 생존, 횡단면은 실패).
무엇보다 **회전이 낮다** — 8403은 하루 2건이라 수수료 부담이 규모의 0.2%다.
15분봉 봇은 5.2%다. 수수료가 엣지를 먹는 우리 문제에서 자유로운 유일한 계열이다.

지금 무엇이 어긋나 있나
─────────────────────
검증은 **보유 480시간(20일)** 기준이었는데 8403은 지금 **24시간**으로 잘려 있다.
일봉 전략을 하루에 자르면 대부분의 청산이 '시간 만료'가 된다. 즉 **검증 범위 밖**이다.

무엇을 재나
  · 보유기간 × 레버리지 격자
  · 개발(앞 절반) / 봉인(뒤 절반) — 양쪽 통과해야 후보
  · **월수익과 함께 최대낙폭을 반드시 같이 본다.**
    레버리지는 수익과 낙폭을 같은 배수로 키운다. 낙폭이 100%에 닿으면 청산이다.
  · 비용 왕복 0.10%(우리 실측)

⚠️ 한계
  · 캐시는 현재 상장 194종목 — **생존편향이 남는다**(우리에게 유리한 쪽)
  · 레버리지 적용은 일간 수익률에 배수를 곱하는 근사다. 실제로는 증거금 관리·
    부분청산·펀딩비가 끼어들어 **실제 낙폭은 이보다 나쁘다.**
  · 낙폭이 −50%를 넘는 조합은 실거래에서 청산·강제해지 위험이 크다.
"""
import math
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_ma_expanded import load_daily_aligned          # noqa: E402

MA_FAST, MA_SLOW = 20, 100
SL_ATR = 3.0
MAX_POS = 3
COST = 0.0010                 # 왕복 0.10%
ANN = 365
HOLDS = (1, 5, 10, 20, 30)    # 보유 상한(일). 8403 현재=1일, 검증 조건=20일
LEVS = (1, 2, 3, 5)


def signals(df):
    """MA20이 MA100을 상향 돌파 → 롱 / 하향 → 숏. 진입은 **다음 봉 시가**."""
    c = df["close"]
    f = c.rolling(MA_FAST).mean().values
    s = c.rolling(MA_SLOW).mean().values
    okv = df["_ok"].values
    atr = df["_atr"].values
    cv = c.values
    out = []
    for t in range(MA_SLOW + 2, len(cv) - 1):
        if not okv[t] or not (np.isfinite(f[t]) and np.isfinite(s[t])
                              and np.isfinite(f[t - 1]) and np.isfinite(s[t - 1])):
            continue
        if f[t - 1] <= s[t - 1] and f[t] > s[t]:
            d = "long"
        elif f[t - 1] >= s[t - 1] and f[t] < s[t]:
            d = "short"
        else:
            continue
        a = atr[t]
        px = cv[t]
        if not (np.isfinite(a) and a > 0 and np.isfinite(px) and px > 0):
            continue
        if SL_ATR * a / px > 0.30:            # 손절폭 과대 — 원 검증과 동일 규칙
            continue
        out.append((t + 1, d, float(a)))
    return out


def run(df, i, d, atr, hold):
    """i봉 시가 진입. (청산봉, 비용차감 손익률). 실패 시 None."""
    o = df["open"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(o)
    if i >= n - 1 or not np.isfinite(o[i]) or o[i] <= 0:
        return None
    e = o[i]
    risk = SL_ATR * atr
    sl = e - risk if d == "long" else e + risk
    tp = e + risk * 10 if d == "long" else e - risk * 10
    end = min(i + hold, n - 1)
    for t in range(i, end + 1):
        if not np.isfinite(h[t]):
            continue
        if d == "long":
            if l[t] <= sl:
                return t, (sl - e) / e - COST
            if h[t] >= tp:
                return t, (tp - e) / e - COST
        else:
            if h[t] >= sl:
                return t, (e - sl) / e - COST
            if l[t] <= tp:
                return t, (e - tp) / e - COST
    px = c[end]
    if not np.isfinite(px):
        return None
    r = (px - e) / e if d == "long" else (e - px) / e
    return end, r - COST


def equity(frames, sigmap, hold, lev, lo, hi):
    """일별 자산곡선. 동시 MAX_POS건, 종목당 1건. 각 포지션은 자본의 1/MAX_POS."""
    allsig = sorted(((i, s, d, a) for s, v in sigmap.items() for i, d, a in v),
                    key=lambda x: x[0])
    busy, open_until, daily = {}, [], {}
    trades = 0
    for i, sym, d, a in allsig:
        if not (lo <= i < hi):
            continue
        open_until = [x for x in open_until if x > i]
        if busy.get(sym, -1) >= i or len(open_until) >= MAX_POS:
            continue
        r = run(frames[sym], i, d, a, hold)
        if r is None:
            continue
        ei, p = r
        # 손익을 보유 일수에 균등 배분한다(자산곡선·낙폭을 재려면 필요)
        span = max(ei - i + 1, 1)
        per = p / span / MAX_POS * lev
        for t in range(i, ei + 1):
            daily[t] = daily.get(t, 0.0) + per
        busy[sym] = ei
        open_until.append(ei)
        trades += 1
    eq = [1.0]
    for t in range(lo, hi):
        eq.append(eq[-1] * (1.0 + daily.get(t, 0.0)))
        if eq[-1] <= 0:
            eq[-1] = 1e-9                      # 청산
            break
    return np.array(eq), trades


def perf(eq, trades, days):
    if len(eq) < 30:
        return None
    total = eq[-1] / eq[0]
    if total <= 0:
        return dict(mon=-1.0, mdd=-1.0, sharpe=-9.9, n=trades, wiped=True)
    mon = total ** (30.0 / len(eq)) - 1
    r = np.diff(eq) / np.maximum(eq[:-1], 1e-12)
    av = r.std(ddof=1) * math.sqrt(ANN)
    ar = total ** (ANN / len(eq)) - 1
    peak = np.maximum.accumulate(eq)
    mdd = ((eq - peak) / peak).min()
    return dict(mon=mon, mdd=mdd, sharpe=ar / av if av > 1e-9 else 0.0,
                n=trades, wiped=False)


def main():
    frames, n = load_daily_aligned()
    print(f"  {len(frames)}종목 · {n}일 · MA{MA_FAST}/{MA_SLOW} · 손절 ATR×{SL_ATR} "
          f"· 동시 {MAX_POS}건 · 왕복비용 {COST*100:.2f}%")
    print("  ⚠ 생존편향 남음 · 레버리지는 일수익 배수 근사(실제 낙폭은 이보다 나쁨)\n")
    sig = {s: signals(d) for s, d in frames.items()}
    tot = sum(len(v) for v in sig.values())
    start = MA_SLOW + 2
    mid = start + (n - start) // 2
    print(f"  신호 {tot}건 · 개발 {start}~{mid}일 / 봉인 {mid}~{n}일")
    print(f"  목표: 월 7~11%\n")

    print(f"    {'보유':<6}{'레버':<6}{'개발 월수익':>11}{'개발 MDD':>10}"
          f"{'봉인 월수익':>11}{'봉인 MDD':>10}{'거래':>7}  판정")
    hits = []
    for hold in HOLDS:
        for lev in LEVS:
            e1, t1 = equity(frames, sig, hold, lev, start, mid)
            e2, t2 = equity(frames, sig, hold, lev, mid, n)
            p1, p2 = perf(e1, t1, mid - start), perf(e2, t2, n - mid)
            if not p1 or not p2:
                continue
            tag = ""
            if p1["wiped"] or p2["wiped"]:
                tag = "  💀청산"
            elif p1["mon"] > 0 and p2["mon"] > 0:
                tag = "  ★양쪽플러스"
                if min(p1["mon"], p2["mon"]) >= 0.07:
                    tag = "  ★★목표달성"
                hits.append((hold, lev, p1, p2))
            star = " ←8403 현재" if (hold == 1 and lev == 2) else (
                   " ←검증조건" if (hold == 20 and lev == 1) else "")
            print(f"    {hold:>3}일 {lev:>3}배 {p1['mon']*100:>10.2f}%{p1['mdd']*100:>9.1f}%"
                  f"{p2['mon']*100:>10.2f}%{p2['mdd']*100:>9.1f}%{p2['n']:>7}{tag}{star}")
        print()
    print(f"  → 양쪽 플러스 {len(hits)}개 / {len(HOLDS)*len(LEVS)}개")
    ok7 = [h for h in hits if min(h[2]['mon'], h[3]['mon']) >= 0.07]
    print(f"  → 양쪽 월 7% 이상 {len(ok7)}개")
    for hold, lev, p1, p2 in ok7:
        print(f"     {hold}일/{lev}배 — 개발 월{p1['mon']*100:.1f}%(MDD{p1['mdd']*100:.0f}%) "
              f"/ 봉인 월{p2['mon']*100:.1f}%(MDD{p2['mdd']*100:.0f}%)")


if __name__ == "__main__":
    main()
