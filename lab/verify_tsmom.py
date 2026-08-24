#!/usr/bin/env python3
"""verify_tsmom.py — 시계열 모멘텀(TSMOM) 재검증

출처
────
Chulwoo Han, Byeongguk Kang, Jehyeon Ryu (2023-12)
"Time-Series and Cross-Sectional Momentum in the Cryptocurrency Market:
 A Comprehensive Analysis under Realistic Assumptions"  SSRN 4675565 / AUT ACFR
  · 거래비용과 일중 가격변동을 반영하면 **많은 모멘텀 포트폴리오가 청산되고**
    통계적으로 유의했던 수익이 유의하지 않게 된다 — 평균수익 t검정만으론 부족하다
  · **시계열 모멘텀은 강한 증거, 횡단면 모멘텀은 약한 증거**
  · 최선 설정 **28일 형성 / 5일 보유**, 매 거래 **15bps** 반영,
    **Sharpe 1.51**(시장 0.84), 2014-01~2023-08. 우수성의 원천은 **하방위험 감소**

왜 이걸 먼저 재검증하나
─────────────────────
mooja의 5필터(①수익률 숫자 ②재현가능 ③비용반영 ④OOS ⑤자체재검증)를 유일하게
전부 통과한 후보다. 그리고 **우리가 264조합 중 유일하게 통과시킨 8403의 MA20/100
일봉과 같은 계열**이다 — 독립적으로 같은 답에 도달했다.

⑥ 알파/베타 분리를 반드시 본다
──────────────────────────
BTC는 2013년 이후 그냥 들고만 있어도 연 93.6%다. "연 112%" 같은 헤드라인은
대부분 전략의 알파가 아니라 BTC 자체의 상승이다. 그래서 **BTC 매수보유와
동일가중 알트 지수를 나란히 놓고** 그보다 나은지를 본다.

무엇을 재나
  · 형성기간 L ∈ {7, 14, 28, 56}일  ×  보유기간 H ∈ {1, 5, 10, 20}일
  · 방향: 롱 온리 / 롱숏 (논문은 롱숏 TSMOM, 우리 봇 현실은 롱 온리도 필요)
  · 사이징: 동일가중 / 역변동성(TSMOM 원형)
  · 비용: 회전 1단위당 15bps(논문) — 우리 실측 5bps보다 3배 보수적
  · 개발(앞 절반) / 봉인(뒤 절반) — **양쪽 통과해야 후보**

겹치는 보유기간 처리
  H일 보유는 표준대로 **중첩 포트폴리오**로 만든다. 즉 t일의 비중은
  최근 H개 신호의 평균이다. 이러면 하루 회전이 대략 1/H로 줄어 비용이 실제와 맞는다.

⚠️ 한계: 캐시는 현재 상장 194종목이라 **생존편향이 남는다**(우리에게 유리한 쪽).
"""
import math
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_ma_expanded import load_daily_aligned          # noqa: E402

TOP_N = 30                     # 유동성 상위 N종목
MIN_DOLLAR_VOL = 2_000_000
LIQ_WINDOW = 30
MIN_LISTED = 365
VOL_WINDOW = 20
TARGET_VOL = 0.60              # 연 목표 변동성(역변동성 사이징용)
MAX_LEV = 1.0
COST_PER_TURN = 0.0015         # 논문 가정 15bps. 우리 실측 편도 5bps보다 보수적
ANN = 365

LOOKBACKS = (7, 14, 28, 56)
HOLDS = (1, 5, 10, 20)


def prep(frames, n):
    """종목별 수익률·유동성·변동성·거래가능 배열."""
    ret, liq, vol, ok, close = {}, {}, {}, {}, {}
    for s, d in frames.items():
        c = d["close"].values.astype(float)
        v = d["volume"].values.astype(float)
        cs = pd.Series(c)
        r = cs.pct_change().values
        close[s] = c
        ret[s] = np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)
        liq[s] = pd.Series(v * c).rolling(LIQ_WINDOW).median().values
        vol[s] = pd.Series(r).rolling(VOL_WINDOW).std().values
        valid = np.where(np.isfinite(c))[0]
        o = np.zeros(n, dtype=bool)
        if len(valid):
            o[valid[0] + MIN_LISTED:] = True
        ok[s] = o
    return ret, liq, vol, ok, close


def tsmom_sign(close, L):
    """t일 종가 기준 과거 L일 수익의 부호. **t+1부터 보유**한다(미래 안 봄)."""
    c = pd.Series(close)
    r = (c / c.shift(L) - 1.0).values
    sgn = np.zeros(len(r))
    sgn[np.isfinite(r) & (r > 0)] = 1.0
    sgn[np.isfinite(r) & (r < 0)] = -1.0
    return sgn


def pool_at(t, syms, liq, ok):
    cand = []
    for s in syms:
        if not ok[s][t]:
            continue
        lq = liq[s][t]
        if not np.isfinite(lq) or lq < MIN_DOLLAR_VOL:
            continue
        cand.append((lq, s))
    cand.sort(reverse=True)
    return [s for _, s in cand[:TOP_N]]


def backtest(frames, n, L, H, mode, sizing, lo, hi, ret, liq, vol, ok, close):
    syms = list(frames)
    sgn = {s: tsmom_sign(close[s], L) for s in syms}
    tgt_daily = TARGET_VOL / math.sqrt(ANN)
    per_cap = MAX_LEV / TOP_N * 2.0

    prev, eq, turn_tot, days = {}, [1.0], 0.0, 0
    for t in range(lo, hi):
        pool = pool_at(t, syms, liq, ok)
        raw = {}
        for s in pool:
            # 중첩 포트폴리오: 최근 H개 신호의 평균 (t까지의 신호만 쓴다)
            w = float(np.mean([sgn[s][max(t - k, 0)] for k in range(H)]))
            if mode == "롱온리":
                w = max(w, 0.0)
            if w == 0.0:
                continue
            if sizing == "동일가중":
                k = MAX_LEV / TOP_N
            else:                                   # 역변동성
                sd = vol[s][t]
                k = (tgt_daily / sd / TOP_N) if (np.isfinite(sd) and sd > 1e-6) else 0.0
            v = w * k
            if abs(v) > per_cap:
                v = math.copysign(per_cap, v)
            if v != 0.0:
                raw[s] = v
        gross = sum(abs(v) for v in raw.values())
        if gross > MAX_LEV:                          # 상한 초과일 때만 축소 = 미달이면 현금
            raw = {s: v * MAX_LEV / gross for s, v in raw.items()}

        turn = sum(abs(raw.get(s, 0.0) - prev.get(s, 0.0)) for s in set(raw) | set(prev))
        turn_tot += turn
        day_r = sum(prev.get(s, 0.0) * ret[s][t] for s in prev) - turn * COST_PER_TURN
        eq.append(eq[-1] * (1.0 + day_r))
        prev = raw
        days += 1
    return np.array(eq), turn_tot / max(days, 1)


def perf(eq):
    r = np.diff(eq) / eq[:-1]
    if len(r) < 30:
        return None
    ar = (eq[-1] / eq[0]) ** (ANN / len(r)) - 1
    av = r.std(ddof=1) * math.sqrt(ANN)
    peak = np.maximum.accumulate(eq)
    return dict(ret=ar, vol=av, sharpe=ar / av if av > 1e-9 else 0.0,
                mdd=((eq - peak) / peak).min())


def bench_btc(frames, lo, hi):
    c = frames["BTC"]["close"].values[lo:hi].astype(float)
    c = c[np.isfinite(c)]
    return perf(c / c[0]) if len(c) > 30 else None


def bench_alt(frames, n, lo, hi, ret, liq, ok):
    """유동성 상위 종목 동일가중 매수보유 — '알트 지수' 대용."""
    syms = list(frames)
    eq = [1.0]
    for t in range(lo, hi):
        pool = pool_at(t, syms, liq, ok)
        if not pool:
            eq.append(eq[-1])
            continue
        eq.append(eq[-1] * (1.0 + sum(ret[s][t] for s in pool) / len(pool)))
    return perf(np.array(eq))


def main():
    frames, n = load_daily_aligned()
    ret, liq, vol, ok, close = prep(frames, n)
    start = max(MIN_LISTED, max(LOOKBACKS) + LIQ_WINDOW)
    mid = start + (n - start) // 2
    print(f"  {len(frames)}종목 · {n}일 · 유동성 상위 {TOP_N} · 비용 회전당 {COST_PER_TURN*1e4:.0f}bps")
    print(f"  개발 {start}~{mid}일 / 봉인 {mid}~{n}일")
    print("  ⚠ 생존편향 남음(현재 상장 종목만) — 결과는 낙관적으로 치우친다\n")

    print("  ■ 벤치마크 (⑥ 알파/베타 분리용)")
    for lo, hi, lbl in ((start, mid, "개발"), (mid, n, "봉인")):
        b = bench_btc(frames, lo, hi)
        a = bench_alt(frames, n, lo, hi, ret, liq, ok)
        print(f"    {lbl}  BTC 매수보유 연{b['ret']*100:+7.1f}% Sharpe{b['sharpe']:+5.2f}"
              f"   |  알트 동일가중 연{a['ret']*100:+7.1f}% Sharpe{a['sharpe']:+5.2f}")
    print()

    for mode in ("롱숏", "롱온리"):
        for sizing in ("역변동성", "동일가중"):
            print(f"  ■ {mode} · {sizing}")
            print(f"    {'형성/보유':<12}{'개발 연수익':>12}{'Sharpe':>9}"
                  f"{'봉인 연수익':>12}{'Sharpe':>9}{'MDD(봉인)':>11}{'회전':>7}")
            hits = []
            for L in LOOKBACKS:
                for H in HOLDS:
                    e1, t1 = backtest(frames, n, L, H, mode, sizing, start, mid,
                                      ret, liq, vol, ok, close)
                    e2, t2 = backtest(frames, n, L, H, mode, sizing, mid, n,
                                      ret, liq, vol, ok, close)
                    p1, p2 = perf(e1), perf(e2)
                    if not p1 or not p2:
                        continue
                    mark = ""
                    if p1["ret"] > 0 and p2["ret"] > 0:
                        mark = "  ★양쪽플러스"
                        hits.append((L, H, p1, p2))
                    star = " ←논문설정" if (L == 28 and H == 5) else ""
                    print(f"    {L:>3}일/{H:>2}일  {p1['ret']*100:>10.1f}%{p1['sharpe']:>9.2f}"
                          f"{p2['ret']*100:>11.1f}%{p2['sharpe']:>9.2f}"
                          f"{p2['mdd']*100:>10.1f}%{t2:>7.2f}{mark}{star}")
            print(f"    → 양쪽 플러스 {len(hits)}개 / {len(LOOKBACKS)*len(HOLDS)}개\n")


if __name__ == "__main__":
    main()
