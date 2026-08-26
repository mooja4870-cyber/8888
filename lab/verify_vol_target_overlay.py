#!/usr/bin/env python3
"""verify_vol_target_overlay.py — 8403(MA20/100)에 변동성 타겟팅을 얹으면 나아지는가

왜 이걸 고르나 — 문헌 조사 결과 대부분의 부가전략이 **기각**됐다
──────────────────────────────────────────────────────────────
· 베타 헤지(알트 롱 + BTC 숏): *Crypto market betas: the limits of predictability and
  hedging* (Financial Innovation, 2025) — 암호자산 베타는 예측력이 낮고 불안정해
  **베타헤지 포트폴리오가 분산을 줄인 종목이 전체의 17%뿐**. 사실상 비트코인 하나.
  Lo의 beta-overlay는 회귀 R²가 높아야 작동하는데 암호시장은 그 조건을 못 맞춘다.
· 시장중립 오버레이: 2026 copula 페어트레이딩 연구 — 최대낙폭은 20% 아래로 눌렀으나
  **거래비용 차감 후 순수익이 마이너스**였고 위험조정수익도 개선되지 않았다.
· 횡단면 모멘텀: 시계열 모멘텀보다 **낙폭이 더 크고** 성과가 낮다(2020-2025 비교연구).
· 우리 자체 기각분: Donchian 앙상블 24/24 실패, TSMOM 롱온리 32/32 실패,
  펀딩비 극단·청산 캐스케이드 기각.

남은 하나가 **변동성 타겟팅**이다. Harvey·Hoyle·Rattray·Sargaison·Van Hemert (2018),
*The Impact of Volatility Targeting* (FAJ) — 실현변동성에 반비례해 노출을 조절하면
낙폭이 줄고 샤프가 개선된다. 다만 선견편향 비판이 있어 **우리 데이터로 확인해야 한다.**

mooja의 반론에 답한다
────────────────────
"노출을 줄이면 수익도 같이 줄어 상쇄 아닌가" — **균일 축소는 맞다.** 기댓값은 선형이다.
변동성 타겟팅은 균일 축소가 아니라 **조건부 축소**다. 변동성이 높을 때만 줄인다.
변동성과 이후 수익 사이에 음의 관계가 있어야만 가치가 생긴다. 그게 있는지를 여기서 잰다.
없으면 기각한다.

무엇을 재나
  기준선  : 검증 통과 설정 그대로(MA20/100, 보유 10일, 동일 비중)
  처치    : 진입 시점 실현변동성(20일)에 반비례해 비중 조절, 목표 변동성 고정
  분할    : 개발(앞 절반) / 봉인(뒤 절반) — **양쪽 다 나아져야 채택**
  비용    : 왕복 0.10%(실측)

⚠️ 한계: 캐시는 현재 상장 종목이라 생존편향이 남는다(우리에게 유리한 쪽).
"""
import math
import sys

import numpy as np

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_ma_expanded import load_daily_aligned          # noqa: E402

MA_FAST, MA_SLOW = 20, 100
SL_ATR = 3.0
HOLD = 10
MAX_POS = 3
COST = 0.0010
ANN = 365
VOL_WIN = 20                    # 실현변동성 측정 창(일)
TARGET_VOLS = (0.40, 0.60, 0.80, 1.00)   # 연환산 목표 변동성
VOL_CAP = 3.0                   # 비중 상한(과도한 레버리지 방지)


def signals(df):
    """MA20 상향돌파→롱 / 하향→숏. 진입은 다음 봉 시가. (검증본과 동일)"""
    c = df["close"]
    f = c.rolling(MA_FAST).mean().values
    s = c.rolling(MA_SLOW).mean().values
    okv = df["_ok"].values
    atr = df["_atr"].values
    cv = c.values
    rv = c.pct_change().rolling(VOL_WIN).std().values * math.sqrt(ANN)  # 연환산 실현변동성
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
        a, px, v = atr[t], cv[t], rv[t]
        if not (np.isfinite(a) and a > 0 and np.isfinite(px) and px > 0):
            continue
        if SL_ATR * a / px > 0.30:
            continue
        out.append((t + 1, d, float(a), float(v) if np.isfinite(v) else float("nan")))
    return out


def run(df, i, d, atr):
    """i봉 시가 진입 → (청산봉, 비용 전 손익률). 검증본과 동일한 청산 규칙."""
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
    end = min(i + HOLD, n - 1)
    for t in range(i, end + 1):
        if not np.isfinite(h[t]):
            continue
        if d == "long":
            if l[t] <= sl:
                return t, (sl - e) / e
            if h[t] >= tp:
                return t, (tp - e) / e
        else:
            if h[t] >= sl:
                return t, (e - sl) / e
            if l[t] <= tp:
                return t, (e - tp) / e
    px = c[end]
    if not np.isfinite(px):
        return None
    return end, ((px - e) / e if d == "long" else (e - px) / e)


def equity(frames, sigmap, lo, hi, target_vol=None):
    """일별 자산곡선. target_vol=None이면 동일 비중(기준선)."""
    allsig = sorted(((i, s, d, a, v) for s, arr in sigmap.items() for i, d, a, v in arr),
                    key=lambda x: x[0])
    busy, open_until, daily = {}, [], {}
    trades, wsum = 0, []
    for i, sym, d, a, v in allsig:
        if not (lo <= i < hi):
            continue
        open_until = [x for x in open_until if x > i]
        if busy.get(sym, -1) >= i or len(open_until) >= MAX_POS:
            continue
        r = run(frames[sym], i, d, a)
        if r is None:
            continue
        ei, p = r
        # ── 비중 결정 ──
        if target_vol is None:
            w = 1.0 / MAX_POS
        else:
            if not (np.isfinite(v) and v > 1e-6):
                continue                       # 변동성 미확정이면 건너뛴다
            w = min(target_vol / v, VOL_CAP) / MAX_POS
        wsum.append(w * MAX_POS)
        span = max(ei - i + 1, 1)
        per = (p - COST) * w / span            # 비용도 비중에 비례
        for t in range(i, ei + 1):
            daily[t] = daily.get(t, 0.0) + per
        busy[sym] = ei
        open_until.append(ei)
        trades += 1
    eq = [1.0]
    for t in range(lo, hi):
        eq.append(eq[-1] * (1.0 + daily.get(t, 0.0)))
        if eq[-1] <= 0:
            eq[-1] = 1e-9
            break
    return np.array(eq), trades, (float(np.mean(wsum)) if wsum else 0.0)


def perf(eq):
    if len(eq) < 30:
        return None
    total = eq[-1] / eq[0]
    if total <= 0:
        return dict(mon=-1.0, mdd=-1.0, sharpe=-9.9, wiped=True)
    r = np.diff(eq) / np.maximum(eq[:-1], 1e-12)
    av = r.std(ddof=1) * math.sqrt(ANN)
    ar = total ** (ANN / len(eq)) - 1
    peak = np.maximum.accumulate(eq)
    return dict(mon=total ** (30.0 / len(eq)) - 1,
                mdd=((eq - peak) / peak).min(),
                sharpe=(ar / av if av > 1e-9 else 0.0), wiped=False)


def main():
    frames, n = load_daily_aligned()
    sig = {s: signals(d) for s, d in frames.items()}
    tot = sum(len(v) for v in sig.values())
    start = MA_SLOW + VOL_WIN + 2
    mid = start + (n - start) // 2
    print(f"  {len(frames)}종목 · {n}일 · MA{MA_FAST}/{MA_SLOW} · 보유 {HOLD}일 · 비용 {COST*100:.2f}%")
    print(f"  신호 {tot}건 · 개발 {start}~{mid}일 / 봉인 {mid}~{n}일")
    print("  ⚠ 생존편향 남음\n")

    print(f"  {'설정':<18}{'개발 월수익':>11}{'개발MDD':>9}{'개발SR':>8}"
          f"{'봉인 월수익':>11}{'봉인MDD':>9}{'봉인SR':>8}{'평균노출':>9}")

    e1, t1, w1 = equity(frames, sig, start, mid)
    e2, t2, w2 = equity(frames, sig, mid, n)
    b1, b2 = perf(e1), perf(e2)
    if not b1 or not b2:
        print("  기준선 산출 실패")
        return 1
    print(f"  {'기준선(동일비중)':<18}{b1['mon']*100:>10.2f}%{b1['mdd']*100:>8.1f}%{b1['sharpe']:>8.2f}"
          f"{b2['mon']*100:>10.2f}%{b2['mdd']*100:>8.1f}%{b2['sharpe']:>8.2f}{w1:>9.2f}")

    hits = []
    for tv in TARGET_VOLS:
        a1, n1, aw1 = equity(frames, sig, start, mid, tv)
        a2, n2, aw2 = equity(frames, sig, mid, n, tv)
        p1, p2 = perf(a1), perf(a2)
        if not p1 or not p2:
            continue
        better_dev = p1["sharpe"] > b1["sharpe"] and p1["mon"] > b1["mon"]
        better_seal = p2["sharpe"] > b2["sharpe"] and p2["mon"] > b2["mon"]
        tag = "  ★양쪽개선" if (better_dev and better_seal) else ""
        if better_dev and better_seal:
            hits.append(tv)
        print(f"  {'변동성타겟 ' + str(int(tv*100)) + '%':<18}{p1['mon']*100:>10.2f}%{p1['mdd']*100:>8.1f}%"
              f"{p1['sharpe']:>8.2f}{p2['mon']*100:>10.2f}%{p2['mdd']*100:>8.1f}%{p2['sharpe']:>8.2f}"
              f"{aw1:>9.2f}{tag}")

    print()
    if hits:
        print(f"  → 개발·봉인 **양쪽에서** 수익과 샤프가 모두 개선된 설정: {hits}")
        print("     다음 단계: 기간 4분할·종목군 분산으로 강건성 재확인 후에만 채택")
    else:
        print("  → 양쪽 개선 0건. **변동성 타겟팅 기각.**")
        print("     노출 조절만으로는 이 전략의 수익성이 바뀌지 않는다(mooja 지적과 일치).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
