#!/usr/bin/env python3
"""verify_200ma_regime.py — "200일선 우상향=롱만 / 우하향=숏만"이 옳은가

mooja 제안
─────────
시황에 따라 방향을 조절하자. 200일 이동평균선이 우상향이면 롱만, 우하향이면 숏만.

웹 조사 요약 (주식 기준)
──────────────────────
· 200일선 **위**: 연 11% · 변동성 14%
· 200일선 **아래**: 연 **9%** · 변동성 **29%**
핵심은 아래에서도 수익률이 **양수**라는 점이다. 기계적으로 숏으로 뒤집으면
양(+)의 표류가 있는 시장을 공매도하는 셈이 된다. 그래서 학술 구현은 대부분
**롱/현금(long-flat)**이지 롱/숏이 아니다. 필터의 값어치는 **변동성 반감**이지
숏 수익이 아니다. 게다가 200일선은 느려서 신호가 늦고, **약세장 반등이 격렬**해
그 지연이 숏 쪽에 특히 불리하게 작용한다.

크립토는 주식과 다를 수 있으므로 여기서 직접 잰다.

두 가지를 나눠 본다
  1) **전제 검정** — 국면별로 롱/숏 원수익이 실제로 갈리는가 (전략 무관)
  2) **적용 검정** — 8403의 이동평균 20/100에 필터를 걸면 나아지는가
     (롱만 / 롱-현금 / 롱-숏 / 필터없음)

판정: 앞절반·뒤절반 양쪽 개선 + 2σ. 최근 180일은 탐색에서 제외.
"""
import sys
import numpy as np, pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_ma_expanded import (load_daily_aligned, ma_cross, run_trade, stat,
                                acct, HOLDOUT_DAYS, MAX_POS)

MA_REG = 200          # 국면 판정 이동평균
SLOPE_N = 20          # 기울기 판정 구간(일)


def regime(df):
    """+1 우상향 / −1 우하향 / 0 미확정. 기울기는 최근 SLOPE_N일 변화로 본다."""
    c = df["close"]
    m = c.rolling(MA_REG).mean().values
    r = np.zeros(len(m))
    for t in range(MA_REG + SLOPE_N, len(m)):
        if not (np.isfinite(m[t]) and np.isfinite(m[t - SLOPE_N])):
            continue
        r[t] = 1 if m[t] > m[t - SLOPE_N] else -1
    return r


def premise_test(frames, SE):
    """전략과 무관하게, 국면별 원수익(롱 기준)을 잰다."""
    print("\n  ■ 1) 전제 검정 — 국면별 원수익 (전략 무관, 롱 기준 %)")
    print(f"    200일선 기울기({SLOPE_N}일 기준)로 나눠 다음 N일 수익을 본다.")
    print(f"    {'구간':<12}{'국면':<10}{'표본':>8}{'+5일':>12}{'+20일':>12}{'+60일':>12}")
    for nm, lo, hi in (("탐색", 0, SE), ("최종확인", SE, None)):
        for want, lab in ((1, "우상향"), (-1, "우하향")):
            acc = {5: [], 20: [], 60: []}
            for s, d in frames.items():
                c = d["close"].values
                rg = regime(d)
                n = len(c)
                end = (hi if hi else n)
                for t in range(lo, min(end, n - 61)):
                    if rg[t] != want or not np.isfinite(c[t]) or c[t] <= 0:
                        continue
                    for k in acc:
                        if np.isfinite(c[t + k]):
                            acc[k].append((c[t + k] - c[t]) / c[t] * 100)
            cells = []
            for k in (5, 20, 60):
                a = np.array(acc[k])
                cells.append(f"{a.mean():+.2f}%" if len(a) > 100 else "부족")
            print(f"    {nm:<12}{lab:<10}{len(acc[5]):>8}{cells[0]:>12}{cells[1]:>12}{cells[2]:>12}")


def apply_test(frames, N, SE):
    """8403 전략(이동평균 20/100)에 국면 필터를 걸어 본다."""
    base = {s: ma_cross(d, 20, 100) for s, d in frames.items()}
    rg = {s: regime(d) for s, d in frames.items()}

    def filt(mode):
        out = {}
        for s, sigs in base.items():
            keep = []
            for t, d in sigs:
                r = rg[s][t]
                if mode == "none":
                    keep.append((t, d))
                elif mode == "long_only":
                    if d == "long":
                        keep.append((t, d))
                elif mode == "long_flat":          # 우상향일 때만 롱
                    if d == "long" and r > 0:
                        keep.append((t, d))
                elif mode == "long_short":         # mooja 제안: 우상향 롱 / 우하향 숏
                    if r > 0 and d == "long":
                        keep.append((t, d))
                    elif r < 0 and d == "short":
                        keep.append((t, d))
            out[s] = keep
        return out

    print("\n  ■ 2) 적용 검정 — 이동평균 20/100에 필터를 걸면")
    print(f"    {'필터':<26}{'앞절반':>26}{'뒤절반':>26}{'최종확인':>26}")
    print("    " + "─" * 104)
    for mode, lab in (("none", "없음 (롱숏 모두)"),
                      ("long_only", "롱만 (국면 무시)"),
                      ("long_flat", "우상향일 때만 롱"),
                      ("long_short", "★우상향 롱 / 우하향 숏")):
        sm = filt(mode)
        a = stat(trades_(frames, sm, 0, SE // 2))
        b = stat(trades_(frames, sm, SE // 2, SE))
        h = stat(trades_(frames, sm, SE, N))
        print(f"    {lab:<26}{f_(a):>26}{f_(b):>26}{f_(h):>26}")


def trades_(frames, sigmap, lo, hi, sl_atr=3.0, hold=20):
    allsig = sorted(((t, s, d) for s, v in sigmap.items() for t, d in v
                     if lo <= t < hi), key=lambda x: x[0])
    busy, openp, out = {}, [], []
    for t, sym, d in allsig:
        openp = [x for x in openp if x > t]
        if busy.get(sym, -1) >= t or len(openp) >= MAX_POS:
            continue
        ei, p = run_trade(frames[sym], t, d, sl_atr, hold)
        if p is None:
            continue
        out.append((t, ei, p))
        busy[sym] = ei
        openp.append(ei)
    return out


def f_(s):
    return "표본부족" if s is None else \
        f"{s['n']:>3}건 {s['mean']:+.2f}±{s['se']:.2f}({s['sigma']:+.1f}σ)"


def main():
    frames, N = load_daily_aligned()
    SE = N - HOLDOUT_DAYS
    print(f"  {len(frames)}종목 · {N}일 · 국면 = {MA_REG}일선 기울기({SLOPE_N}일)")
    print(f"  탐색 0~{SE}일 · 최종확인 {SE}~{N}일")
    premise_test(frames, SE)
    apply_test(frames, N, SE)
    print("\n  ※ 주식 문헌: 200일선 위 연11%/변동성14%, 아래 연9%/변동성29%.")
    print("     아래에서도 수익률이 **양수**라 기계적 숏 전환은 역효과라는 것이 요지.")


if __name__ == "__main__":
    main()
