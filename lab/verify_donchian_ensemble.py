#!/usr/bin/env python3
"""verify_donchian_ensemble.py — Zarattini·Pagani·Barbon(2025) 방식 재현·검증

출처
────
Carlo Zarattini, Alberto Pagani, Andrea Barbon,
"Catching Crypto Trends; A Tactical Approach for Bitcoin and Altcoins"
Swiss Finance Institute Research Paper No. 25-80 (2025-04-08)
  · 여러 기간의 **돈치안 채널 추세모형을 앙상블**로 합치고
  · **변동성 기반 포지션 사이징**을 얹는다
  · 종목은 **거래대금 상위 20** · 30일 중앙 거래대금 $2M 이상 · 상장 1년 이상
  · **롱 온리**
  · 보고 성과: 수수료 차감 후 **Sharpe > 1.5**, BTC 대비 연 알파 **10.8%**
  · 자료는 **생존편향 제거** 전 종목, 2015년 이후

왜 이걸 재현하나
──────────────
우리 15분봉 봇은 실거래 건당 엣지가 마이너스다. 문헌이 가리키는 원인은 분명하다:
크립토 모멘텀은 **형성 1~4주 / 지속 1주**에서 작동하는데 우리는 하루 60건을 돈다.
왕복 비용 0.10%는 문헌이 "26~30bps 넘으면 죽는다"고 한 선의 3배 이상이다.
회전을 줄이는 것 말고 길이 없다.

⚠️ 이 재현의 한계 — 결과를 낙관적으로 만든다
  · **생존편향이 남아 있다.** 캐시는 지금 상장돼 있는 194종목뿐이다.
    상장폐지된 코인이 빠져 있어 원논문보다 유리하게 나온다.
  · 4시간봉 6개를 합쳐 일봉으로 만들었다. 원논문의 일봉과 미세하게 다를 수 있다.
  · 거래대금은 코인 수량×종가로 근사했다(체결 기준 달러 거래대금이 아니다).
  · 자료가 최대 3년이라 2015년 이후를 다 보지 못한다.
따라서 **"논문 수치를 재현했다"가 아니라 "우리 종목·기간에서 이 방식이 통하나"**를 본다.

무엇을 재나
  · 개발(앞 절반) / 봉인(뒤 절반) 분할 — 양쪽 모두 통과해야 후보로 올린다
  · 사이징 4종 비교(문헌이 갈리는 지점이라 직접 가른다)
      S1 동일가중        S2 역(총)변동성
      S3 역(하방)변동성   S4 조건부(극단 구간에서만 조정)
  · 비용 왕복 0.10%(우리 실측)와 0.15%(논문 가정) 둘 다
  · 대조군: BTC 매수보유 · 돈치안 단일기간

판정: 봉인 구간 Sharpe가 **BTC 매수보유보다 높고**, 개발 구간에서도 그래야 한다.
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_ma_expanded import load_daily_aligned          # noqa: E402

# ── 논문 조건 ──
LOOKBACKS = (20, 40, 80, 160)     # 앙상블에 쓰는 돈치안 진입 기간(일)
EXIT_DIV = 2                      # 청산은 진입기간의 절반 (돈치안 원형)
TOP_N = 20                        # 거래대금 상위 20종목
MIN_DOLLAR_VOL = 2_000_000        # 30일 중앙 거래대금 $2M
LIQ_WINDOW = 30
MIN_LISTED = 365                  # 상장 1년 이상
VOL_WINDOW = 20                   # 변동성 추정 기간
TARGET_VOL = 0.60                 # 연 60% 목표 변동성(크립토 기준). 사이징 비교용
MAX_LEV = 1.0                     # 총 노출 상한(레버리지 없음)
COSTS = (0.0010, 0.0015)          # 왕복 0.10%(실측) / 0.15%(논문 가정)
ANN = 365


# ────────────────────────── 신호 ──────────────────────────
def donchian_state(close, high, low, L):
    """돈치안 추세 상태 0/1. 상단 돌파로 진입, 하단(L/2) 이탈로 청산.

    **모든 판정은 전일까지의 값으로 한다**(shift). 당일 고가를 보고 당일 사는 건
    미래를 보는 것이다 — 이걸 틀려 한 주를 날린 적이 있다.
    """
    n = len(close)
    up = pd.Series(high).rolling(L).max().shift(1).values
    dn = pd.Series(low).rolling(max(L // EXIT_DIV, 2)).min().shift(1).values
    st = np.zeros(n)
    on = 0
    for t in range(n):
        c = close[t]
        if not np.isfinite(c):
            st[t] = on
            continue
        if on == 0 and np.isfinite(up[t]) and c > up[t]:
            on = 1
        elif on == 1 and np.isfinite(dn[t]) and c < dn[t]:
            on = 0
        st[t] = on
    return st


def build(frames, n):
    """종목별 (앙상블 신호, 일수익률, 유동성, 변동성, 하방변동성, 거래가능)."""
    sig, ret, liq, vol, dvol, ok = {}, {}, {}, {}, {}, {}
    for s, d in frames.items():
        c = d["close"].values.astype(float)
        h = d["high"].values.astype(float)
        l = d["low"].values.astype(float)
        v = d["volume"].values.astype(float)
        # 앙상블 = 여러 기간 돈치안 상태의 평균 (0~1)
        e = np.zeros(n)
        for L in LOOKBACKS:
            e += donchian_state(c, h, l, L)
        sig[s] = e / len(LOOKBACKS)

        cs = pd.Series(c)
        r = cs.pct_change().values
        ret[s] = np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)
        liq[s] = pd.Series(v * c).rolling(LIQ_WINDOW).median().values
        vol[s] = pd.Series(r).rolling(VOL_WINDOW).std().values
        neg = pd.Series(np.where(r < 0, r, 0.0))
        dvol[s] = neg.rolling(VOL_WINDOW).std().values

        valid = np.where(np.isfinite(c))[0]
        o = np.zeros(n, dtype=bool)
        if len(valid):
            o[valid[0] + MIN_LISTED:] = True       # 상장 1년 이후만
        ok[s] = o
    return sig, ret, liq, vol, dvol, ok


# ────────────────────────── 사이징 ──────────────────────────
def weights(mode, syms, t, sig, vol, dvol):
    """선택된 종목들의 목표 비중.

    ⚠️ 여기가 추세추종의 급소다. 비중을 **항상 100%가 되도록 정규화하면 안 된다.**
    그렇게 하면 추세가 한 종목만 살아 있어도 그 하나에 전액을 넣는다 — 하락장에서
    가장 위험한 행동이다. 추세가 없으면 **현금으로 비어 있어야** 한다.
    그래서 종목마다 독립적으로 비중을 정하고, 합계가 상한을 넘을 때만 눌러 담는다.
    """
    per_cap = MAX_LEV / TOP_N * 2.0        # 한 종목 상한(집중 방지)
    tgt_daily = TARGET_VOL / math.sqrt(ANN)
    raw = {}
    for s in syms:
        w = sig[s][t]                      # 0~1 앙상블 동의율
        if w <= 0:
            continue
        if mode == "S1 동일가중":
            k = MAX_LEV / TOP_N
        elif mode == "S2 역변동성":
            sd = vol[s][t]
            k = (tgt_daily / sd / TOP_N) if (np.isfinite(sd) and sd > 1e-6) else 0.0
        elif mode == "S3 역하방변동성":
            sd = dvol[s][t]
            k = (tgt_daily / sd / TOP_N) if (np.isfinite(sd) and sd > 1e-6) else 0.0
        elif mode == "S4 조건부":
            # 극단 구간에서만 조정한다(Conditional Volatility Targeting).
            sd = vol[s][t]
            if not np.isfinite(sd) or sd <= 1e-6:
                k = 0.0
            else:
                ann = sd * math.sqrt(ANN)
                mult = 0.5 if ann > TARGET_VOL * 1.5 else (1.5 if ann < TARGET_VOL * 0.5 else 1.0)
                k = MAX_LEV / TOP_N * mult
        else:
            k = MAX_LEV / TOP_N
        v = min(w * k, per_cap)
        if v > 0:
            raw[s] = v
    tot = sum(raw.values())
    if tot > MAX_LEV:                      # 상한 초과일 때만 축소. 미달이면 그대로 = 현금 보유
        raw = {s: v * MAX_LEV / tot for s, v in raw.items()}
    return raw


# ────────────────────────── 백테스트 ──────────────────────────
def backtest(frames, n, mode, cost, lo, hi, sig, ret, liq, vol, dvol, ok):
    syms = list(frames)
    prev = {}
    eq = [1.0]
    turn_tot = 0.0
    days = 0
    for t in range(lo, hi):
        # 유동성 심사 — 상위 TOP_N만
        cand = []
        for s in syms:
            if not ok[s][t]:
                continue
            lq = liq[s][t]
            if not np.isfinite(lq) or lq < MIN_DOLLAR_VOL:
                continue
            cand.append((lq, s))
        cand.sort(reverse=True)
        pool = [s for _, s in cand[:TOP_N]]

        tgt = weights(mode, pool, t, sig, vol, dvol)
        turn = sum(abs(tgt.get(s, 0.0) - prev.get(s, 0.0)) for s in set(tgt) | set(prev))
        turn_tot += turn
        # 당일 수익은 **전일 비중**으로 얻는다(당일 신호로 당일 수익을 얻을 수 없다)
        day_r = sum(prev.get(s, 0.0) * ret[s][t] for s in prev)
        day_r -= turn * (cost / 2.0)      # 왕복 cost → 한 방향 cost/2
        eq.append(eq[-1] * (1.0 + day_r))
        prev = tgt
        days += 1
    return np.array(eq), turn_tot / max(days, 1)


def perf(eq, label, turnover=None):
    r = np.diff(eq) / eq[:-1]
    if len(r) < 30:
        return None
    ann_ret = (eq[-1] / eq[0]) ** (ANN / len(r)) - 1
    ann_vol = r.std(ddof=1) * math.sqrt(ANN)
    sharpe = ann_ret / ann_vol if ann_vol > 1e-9 else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = ((eq - peak) / peak).min()
    return dict(label=label, ret=ann_ret, vol=ann_vol, sharpe=sharpe,
                mdd=mdd, turn=turnover)


def line(p):
    if p is None:
        return f"    {'표본부족':<22}"
    t = f"{p['turn']:.2f}" if p["turn"] is not None else "—"
    return (f"    {p['label']:<20} 연수익 {p['ret']*100:+7.1f}%  변동성 {p['vol']*100:5.1f}%  "
            f"Sharpe {p['sharpe']:+5.2f}  최대낙폭 {p['mdd']*100:6.1f}%  회전 {t}")


def buyhold(frames, n, lo, hi, sym="BTC"):
    d = frames.get(sym)
    if d is None:
        return None
    c = d["close"].values[lo:hi].astype(float)
    c = c[np.isfinite(c)]
    if len(c) < 30:
        return None
    return perf(c / c[0], f"{sym} 매수보유")


def main():
    frames, n = load_daily_aligned()
    print(f"  {len(frames)}종목 · {n}일 (4시간봉 6개=1일)")
    print(f"  돈치안 앙상블 {LOOKBACKS} · 청산 1/{EXIT_DIV} · 상위 {TOP_N}종목 "
          f"· 30일 거래대금 ${MIN_DOLLAR_VOL/1e6:.0f}M↑ · 상장 {MIN_LISTED}일↑")
    print("  ⚠ 생존편향 남음(현재 상장 종목만) — 결과는 낙관적으로 치우친다\n")

    print("  지표 계산 중...", flush=True)
    sig, ret, liq, vol, dvol, ok = build(frames, n)

    start = max(MIN_LISTED, max(LOOKBACKS) + LIQ_WINDOW)
    mid = start + (n - start) // 2
    print(f"  개발 = {start}~{mid}일 / 봉인 = {mid}~{n}일\n")

    for cost in COSTS:
        print(f"  ══ 왕복 비용 {cost*100:.2f}% ══")
        for wlo, whi, wname in ((start, mid, "개발 앞절반"), (mid, n, "봉인 뒤절반")):
            print(f"  ■ {wname}")
            bh = buyhold(frames, n, wlo, whi)
            if bh:
                print(line(bh))
            for mode in ("S1 동일가중", "S2 역변동성", "S3 역하방변동성", "S4 조건부"):
                eq, tv = backtest(frames, n, mode, cost, wlo, whi,
                                  sig, ret, liq, vol, dvol, ok)
                print(line(perf(eq, mode, tv)))
            print()


if __name__ == "__main__":
    main()
