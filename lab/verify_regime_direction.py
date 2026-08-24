#!/usr/bin/env python3
"""verify_regime_direction.py — 상승장 롱 / 하락장 숏 게이트가 정말 나은가

mooja 질문
─────────
숏을 그냥 허용하는 게 아니라, **상승장엔 롱만 · 하락장엔 숏만** 하면
수익이 더 나아지지 않겠나.

왜 그냥 믿으면 안 되나 (문헌)
────────────────────────────
· 국면 필터의 이득은 대개 **수익 증가가 아니라 위험 감소**다. 지수처럼 우상향하는
  자산에서 필터는 낙폭을 줄이지 수익을 늘리지 않는다.
· **유효 표본이 극단적으로 작다.** 거래가 1,000건이어도 국면 전환은 20년에 10~15번뿐이라
  국면 규칙은 과최적화되기 가장 쉬운 부류다. 실거래에서 필터 없느니만 못한 사례가 흔하다.
· 방향보다 **변동성 국면이 훨씬 잘 탐지된다**(변동성 군집이 가장 강한 통계적 효과).
· 크립토 한정 학계 결과는 갈린다 — "모멘텀 알파는 숏 다리에서 나온다"는 쪽과
  "롱-숏 구성이 롱 온리보다 못하다"는 쪽이 공존한다.
따라서 **직접 재는 수밖에 없다.**

무엇을 재나
  · 자료: 실제 봇과 동일한 **15분봉 61종목 180일** (lab_cache_live)
  · 신호: 세력흔적 X1~X5 + 세력라인·마지노선 (롱, 그리고 대칭 숏)
  · 진입: **다음 봉 시가** (신호봉 종가가 아니다 — 이걸 틀려 한 주를 날린 적이 있다)
  · 청산: 마지노선 손절 / +5% 익절 / 24시간 만료
  · 비용: 왕복 **0.10%** (테이커 0.05% × 2). 지금 문제의 핵심이 비용이라 반드시 넣는다
  · 제약: 동시 3포지션, 종목당 1건 — 실제 봇과 같게

국면 정의를 여럿 쓴다 (하나만 쓰면 그 하나에 맞춘 셈이 된다)
  R1  BTC가 자기 7일 이동평균 위/아래
  R2  BTC가 자기 20일 이동평균 위/아래
  R3  BTC 24시간 수익률 부호
  R4  시장 폭 — 자기 7일선 위에 있는 종목 비율 (>55% 상승 / <45% 하락)

정책
  P1 롱 only (현행)      P2 숏 only          P3 롱+숏 무조건
  P4 게이트: 상승→롱 / 하락→숏 / 횡보→관망
  P5 게이트: 상승→롱 / 하락→숏 / 횡보→둘 다
  P6 역게이트: 상승→숏 / 하락→롱  ← 헛것을 잡고 있는지 보는 대조군

판정: 개발(앞 90일)·봉인(뒤 90일) **둘 다** 현행보다 나아야 채택 후보.
      한쪽만 좋으면 우연이다.
"""
import glob
import json
import math
import os
import sys

import numpy as np
import pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_live"
BAR_MIN = 15
BARS_DAY = 96
N_BREAK, N_VOL, ATR_LEN = 15, 20, 10
M_FAST, M_SLOW = 1.9, 1.96
TP_PCT = 0.05
MAX_HOLD = 96            # 24시간
MAX_POS = 3
COST = 0.0010            # 왕복 테이커 0.10%
WARM = 300               # 지표 워밍업 봉수


# ────────────────────────────── 자료 ──────────────────────────────
def load():
    frames = {}
    for p in sorted(glob.glob(os.path.join(CACHE, "*.json"))):
        sym = os.path.basename(p).split("_")[-1].replace(".json", "")
        try:
            rows = json.load(open(p))
        except ValueError:
            continue
        if not rows or len(rows) < WARM + 500:
            continue
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        frames[sym] = df
    # 모든 종목을 공통 타임스탬프 격자에 맞춘다 — 국면과 신호의 시각을 일치시켜야 한다
    grid = None
    for df in frames.values():
        s = set(df["ts"])
        grid = s if grid is None else (grid & s)
    grid = np.array(sorted(grid))
    out = {}
    for sym, df in frames.items():
        d = df[df["ts"].isin(grid)].reset_index(drop=True)
        if len(d) == len(grid):
            out[sym] = d
    return out, grid


# ────────────────────────────── 지표 ──────────────────────────────
def atr(df, n):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean().values


def supertrend(df, mult, a):
    """세력라인·마지노선. 밴드 잠금까지 원형대로 — 봇의 _sniper_line과 같다."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    n = len(c)
    line = np.full(n, np.nan)
    ub = lb = np.nan
    dirn = 1
    for t in range(1, n):
        if not np.isfinite(a[t]):
            continue
        src = (h[t] + l[t]) / 2.0
        u, d = src + mult * a[t], src - mult * a[t]
        ub = u if (not np.isfinite(ub) or u < ub or c[t - 1] > ub) else ub
        lb = d if (not np.isfinite(lb) or d > lb or c[t - 1] < lb) else lb
        if c[t] > ub:
            dirn = 1
        elif c[t] < lb:
            dirn = -1
        line[t] = lb if dirn == 1 else ub
    return line


def signals(df):
    """(진입봉 인덱스, 방향, 손절가) 목록. 진입은 t+1 시가이므로 인덱스는 t+1."""
    c, o = df["close"].values, df["open"].values
    h, l, v = df["high"].values, df["low"].values, df["volume"].values
    cs = pd.Series(c)
    hi_c = cs.rolling(N_BREAK).max().shift(1).values
    hi_cp = cs.rolling(N_BREAK).max().shift(2).values
    lo_c = cs.rolling(N_BREAK).min().shift(1).values
    lo_cp = cs.rolling(N_BREAK).min().shift(2).values
    hi_h = pd.Series(h).rolling(N_BREAK).max().shift(1).values
    lo_l = pd.Series(l).rolling(N_BREAK).min().shift(1).values
    vema = pd.Series(v).ewm(span=N_VOL, adjust=False).mean().values
    a = atr(df, ATR_LEN)
    fast, slow = supertrend(df, M_FAST, a), supertrend(df, M_SLOW, a)

    out = []
    for t in range(WARM, len(c) - 2):
        if not (np.isfinite(hi_c[t]) and np.isfinite(vema[t])
                and np.isfinite(fast[t]) and np.isfinite(slow[t])):
            continue
        mid = (hi_h[t] + lo_l[t]) / 2.0
        px = c[t]
        if (px > hi_c[t] and c[t - 1] < hi_cp[t] and px > o[t]
                and v[t] > vema[t] and px > mid
                and px > fast[t] and px > slow[t]):
            out.append((t + 1, "long", float(slow[t])))
        elif (px < lo_c[t] and c[t - 1] > lo_cp[t] and px < o[t]
                and v[t] > vema[t] and px < mid
                and px < fast[t] and px < slow[t]):
            out.append((t + 1, "short", float(slow[t])))
    return out


def run_trade(df, i, direction, sl):
    """i봉 시가 진입. (청산봉, 비용차감 손익률). 실패 시 None."""
    o = df["open"].values
    h, l = df["high"].values, df["low"].values
    n = len(o)
    if i >= n - 1:
        return None
    entry = float(o[i])
    if entry <= 0:
        return None
    if direction == "long":
        tp = entry * (1 + TP_PCT)
        if sl >= entry:
            sl = entry * 0.98
    else:
        tp = entry * (1 - TP_PCT)
        if sl <= entry:
            sl = entry * 1.02
    end = min(i + MAX_HOLD, n - 1)
    for t in range(i, end + 1):
        if direction == "long":
            if l[t] <= sl:
                return t, (sl - entry) / entry - COST
            if h[t] >= tp:
                return t, (tp - entry) / entry - COST
        else:
            if h[t] >= sl:
                return t, (entry - sl) / entry - COST
            if l[t] <= tp:
                return t, (entry - tp) / entry - COST
    px = float(df["close"].values[end])
    r = (px - entry) / entry if direction == "long" else (entry - px) / entry
    return end, r - COST


# ────────────────────────────── 국면 ──────────────────────────────
def regimes(frames, n):
    """국면 배열 4종. +1 상승 / 0 횡보 / −1 하락."""
    reg = {}
    btc = frames.get("BTC")
    if btc is not None:
        c = btc["close"]
        for name, days in (("R1 BTC 7일선", 7), ("R2 BTC 20일선", 20)):
            ma = c.rolling(days * BARS_DAY).mean().values
            cv = c.values
            r = np.zeros(n)
            ok = np.isfinite(ma)
            r[ok & (cv > ma)] = 1
            r[ok & (cv < ma)] = -1
            reg[name] = r
        ret = c.pct_change(BARS_DAY).values
        r = np.zeros(n)
        r[np.isfinite(ret) & (ret > 0.005)] = 1
        r[np.isfinite(ret) & (ret < -0.005)] = -1
        reg["R3 BTC 24h 수익"] = r

    # R4 시장 폭 — 자기 7일선 위에 있는 종목 비율
    above = np.zeros(n)
    cnt = np.zeros(n)
    for df in frames.values():
        c = df["close"]
        ma = c.rolling(7 * BARS_DAY).mean().values
        cv = c.values
        ok = np.isfinite(ma)
        above[ok] += (cv[ok] > ma[ok]).astype(float)
        cnt[ok] += 1
    frac = np.divide(above, np.maximum(cnt, 1))
    r = np.zeros(n)
    r[(cnt > 0) & (frac > 0.55)] = 1
    r[(cnt > 0) & (frac < 0.45)] = -1
    reg["R4 시장 폭"] = r
    return reg


# ────────────────────────────── 시뮬 ──────────────────────────────
POLICIES = {
    "P1 롱 only (현행)":        lambda d, g: d == "long",
    "P2 숏 only":               lambda d, g: d == "short",
    "P3 롱+숏 무조건":           lambda d, g: True,
    "P4 게이트(횡보 관망)":      lambda d, g: (g > 0 and d == "long") or (g < 0 and d == "short"),
    "P5 게이트(횡보 둘다)":      lambda d, g: (g > 0 and d == "long") or (g < 0 and d == "short") or g == 0,
    "P6 역게이트(대조군)":       lambda d, g: (g > 0 and d == "short") or (g < 0 and d == "long"),
}


def simulate(frames, sigmap, reg, policy, lo, hi):
    """[lo, hi) 구간의 거래 손익 목록."""
    allsig = sorted(((i, s, d, sl) for s, v in sigmap.items() for i, d, sl in v),
                    key=lambda x: x[0])
    busy, openp, pnl = {}, [], []
    for i, sym, d, sl in allsig:
        if not (lo <= i < hi):
            continue
        if not policy(d, reg[i]):
            continue
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        r = run_trade(frames[sym], i, d, sl)
        if r is None:
            continue
        ei, p = r
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def stat(v):
    if len(v) < 5:
        return None
    a = np.array(v) * 100
    se = a.std(ddof=1) / math.sqrt(len(a))
    return {"n": len(a), "mean": a.mean(), "win": 100 * (a > 0).mean(),
            "se": se, "sig": a.mean() / se if se > 0 else 0, "sum": a.sum()}


def fmt(s):
    if s is None:
        return "      표본부족"
    return f"{s['n']:>5}건 승{s['win']:>2.0f}% {s['mean']:+.4f}±{s['se']:.4f}({s['sig']:+.1f}σ)"


def main():
    frames, grid = load()
    n = len(grid)
    days = n / BARS_DAY
    print(f"  {len(frames)}종목 · {n}봉({days:.0f}일) · 15분봉 · 왕복비용 {COST*100:.2f}%")

    print("  신호 계산 중...", flush=True)
    sigmap = {s: signals(d) for s, d in frames.items()}
    tot = sum(len(v) for v in sigmap.values())
    nl = sum(1 for v in sigmap.values() for _, d, _ in v if d == "long")
    print(f"  신호 {tot}건 (롱 {nl} / 숏 {tot-nl})")

    reg = regimes(frames, n)
    mid = WARM + (n - WARM) // 2
    print(f"  개발 = 봉 {WARM}~{mid} / 봉인 = 봉 {mid}~{n}\n")

    for rname, r in reg.items():
        d1 = int((r[WARM:] == 1).sum()); d0 = int((r[WARM:] == 0).sum())
        dm = int((r[WARM:] == -1).sum()); tt = max(d1 + d0 + dm, 1)
        print(f"  ■ {rname}  (상승 {100*d1/tt:.0f}% / 횡보 {100*d0/tt:.0f}% / 하락 {100*dm/tt:.0f}%)")
        print(f"    {'정책':<22}{'개발 앞90일':>38}{'봉인 뒤90일':>38}")
        base_dev = base_seal = None
        for pname, pol in POLICIES.items():
            sd = stat(simulate(frames, sigmap, r, pol, WARM, mid))
            ss = stat(simulate(frames, sigmap, r, pol, mid, n))
            if pname.startswith("P1"):
                base_dev, base_seal = sd, ss
            mark = ""
            if base_dev and base_seal and sd and ss and not pname.startswith("P1"):
                if sd["mean"] > base_dev["mean"] and ss["mean"] > base_seal["mean"]:
                    mark = "  ★양쪽개선"
            print(f"    {pname:<22}{fmt(sd):>38}{fmt(ss):>38}{mark}")
        print()


if __name__ == "__main__":
    main()
