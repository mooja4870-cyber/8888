#!/usr/bin/env python3
"""verify_sniper_full.py — '15분봉 세력 흔적' 기법 완전 복원 검증

문서에 없던 것을 추정해 채웠다
────────────────────────────
`15분봉_세력_흔적_찾기_단타_매매_기법_가이드.pdf`는 세 요소 중 신호 수식만
완전히 명세하고, 세력라인·마지노선은 **"승수 1.9 / 1.96"만 있고 원식이 없다.**

웹 조사로 원식을 추정했다. 단서가 슈퍼트렌드와 정확히 맞는다:
  · 승수(Multiplier)가 핵심 파라미터이고 통상 1.5~3.0 범위 (1.9가 그 안)
  · 점선으로 그리는 것이 표준 표시 방식 (문서: 원형 굵은 점선)
  · 가격이 돌파하면 저항선이 **뒤집혀 지지선**이 됨 (문서: 세력라인=저항, 마지노선=지지)
  · 영웅문에 내장돼 있지 않아 수식관리자로 직접 만들어야 함 (문서의 제작 절차와 일치)
  · 두 선이 같은 식에 승수만 다름 → 1.9는 먼저 뒤집히고 1.96은 뒤늦게 확인

    상단 = (H+L)/2 + 승수 × ATR
    하단 = (H+L)/2 − 승수 × ATR   (돌파 방향에 따라 전환·계단식 유지)

확실하지 않으므로 **후보 3종을 전부 잰다**: 슈퍼트렌드 / 볼린저 / 켈트너.
어느 것도 통과하지 못하면 원식을 정확히 구해와도 결과가 달라지기 어렵다.

문서의 4원칙 그대로 구현
  원칙1 15분봉 종가가 세력라인·마지노선 **둘 다** 상향 돌파
  원칙2 같은 봉에 신호 수식(X1~X5) 발생
  원칙3 조건 충족 시 즉시 매수 (여기서는 다음 봉 시가 = 실거래 가능 가격)
  원칙4 **마지노선을 종가로 하향 이탈하면 전량 손절**
  + 분할익절: +5% 도달 시 절반 실현(문서 3페이지)
"""
import glob, json, os, sys
import numpy as np, pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_live"
FEE, SLIP, MAX_POS = 0.001, 0.0002, 3
N_BREAK, N_VOL, MAX_HOLD = 15, 20, 96
M_FAST, M_SLOW = 1.9, 1.96


def load():
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/okx_15m_*.json")):
        s = os.path.basename(p).replace("okx_15m_", "").replace(".json", "")
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        c, h, l = df["close"], df["high"], df["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=10, adjust=False).mean()     # 슈퍼트렌드 기본 기간 10
        out[s] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


# ── 세력라인·마지노선 후보 3종 ────────────────────────────────────────────
def line_supertrend(df, mult):
    """슈퍼트렌드 — 밴드 잠금(계단식 유지)까지 원형대로."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    a = df["_atr"].values
    n = len(c)
    line = np.full(n, np.nan)
    ub = lb = np.nan
    dirn = 1
    for t in range(n):
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


def line_bollinger(df, mult, period=20):
    c = df["close"]
    m, sd = c.rolling(period).mean(), c.rolling(period).std()
    return (m - mult * sd).values          # 지지선 형태로 통일


def line_keltner(df, mult, period=20):
    c = df["close"]
    m = c.ewm(span=period, adjust=False).mean().values
    return m - mult * df["_atr"].values


LINES = {"슈퍼트렌드": line_supertrend, "볼린저": line_bollinger, "켈트너": line_keltner}


def signals_x(df):
    """문서 4페이지 신호 수식 X1~X5. 완성봉 기준."""
    c, o, h, l, v = (df["close"].values, df["open"].values, df["high"].values,
                     df["low"].values, df["volume"].values)
    cs = pd.Series(c)
    hi_c = cs.rolling(N_BREAK).max().shift(1).values
    hi_c_prev = cs.rolling(N_BREAK).max().shift(2).values
    hi_h = pd.Series(h).rolling(N_BREAK).max().shift(1).values
    lo_l = pd.Series(l).rolling(N_BREAK).min().shift(1).values
    vema = pd.Series(v).ewm(span=N_VOL, adjust=False).mean().values
    ok = np.zeros(len(c), dtype=bool)
    for t in range(N_BREAK + N_VOL + 2, len(c) - 1):
        if not (np.isfinite(hi_c[t]) and np.isfinite(hi_c_prev[t])):
            continue
        ok[t] = (c[t] > hi_c[t] and c[t - 1] < hi_c_prev[t] and c[t] > o[t]
                 and v[t] > vema[t] and c[t] > (hi_h[t] + lo_l[t]) / 2.0)
    return ok


def entries(df, kind, use_lines=True):
    """원칙1+2: 두 라인 종가 돌파 & 신호 수식 동시 발생."""
    x = signals_x(df)
    c = df["close"].values
    if not use_lines:
        return [t for t in range(len(c) - 1) if x[t]], None, None
    fast = LINES[kind](df, M_FAST)
    slow = LINES[kind](df, M_SLOW)
    out = []
    for t in range(len(c) - 1):
        if not x[t]:
            continue
        if not (np.isfinite(fast[t]) and np.isfinite(slow[t])):
            continue
        if c[t] > fast[t] and c[t] > slow[t]:
            out.append(t)
    return out, fast, slow


def run_trade(df, t, slow, tp1=0.05, part=0.5):
    """원칙3 진입(다음 봉 시가) · 원칙4 마지노선 종가 이탈 시 전량 손절 · +5% 절반 익절."""
    o, h, c = df["open"].values, df["high"].values, df["close"].values
    n = len(c)
    i = t + 1
    if i >= n or not np.isfinite(o[i]) or o[i] <= 0:
        return i, None
    e = o[i] * (1 + SLIP)
    booked, remain = 0.0, 1.0
    end = min(n - 1, i + MAX_HOLD)
    j = i
    while j <= end:
        if remain == 1.0 and (h[j] - e) / e >= tp1:      # 분할익절
            booked += tp1 * part
            remain = 1.0 - part
        if np.isfinite(slow[j]) and c[j] < slow[j]:      # 마지노선 종가 이탈 → 전량 손절
            return j, booked + (c[j] - e) / e * remain - FEE - SLIP
        j += 1
    k = min(j, end)
    return k, booked + (c[k] - e) / e * remain - FEE - SLIP


def sim(frames, ent, lines, lo, hi):
    allsig = sorted(((t, s) for s, v in ent.items() for t in v if lo <= t < hi),
                    key=lambda x: x[0])
    busy, openp, pnl = {}, [], []
    for t, sym in allsig:
        openp = [x for x in openp if x > t]
        if busy.get(sym, -1) >= t or len(openp) >= MAX_POS:
            continue
        ei, p = run_trade(frames[sym], t, lines[sym])
        if p is None:
            continue
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def st_(p):
    if len(p) < 20:
        return None
    a = np.array(p) * 100
    return {"n": len(a), "mean": a.mean(), "win": 100 * (a > 0).mean(),
            "se": a.std(ddof=1) / np.sqrt(len(a)),
            "sig": a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))}


def f_(s):
    return "표본부족" if s is None else \
        f"{s['n']:>4}건 승{s['win']:>2.0f}% {s['mean']:+.3f}±{s['se']:.3f}({s['sig']:+.1f}σ)"


def main():
    frames = load()
    n0 = len(next(iter(frames.values())))
    mid = n0 // 2
    print(f"  {len(frames)}종목 · {n0}봉(15분) = 180일")
    print(f"  문서 4원칙 그대로 · 두 라인 승수 {M_FAST}/{M_SLOW} · 진입=다음 봉 시가")
    print(f"  청산=마지노선 종가 이탈(원칙4) · +5% 절반 익절(문서 3페이지)")
    print("\n  " + "═" * 74)
    print(f"  {'라인 후보':<14}{'봉인 앞90일':>30}{'개발 뒤90일':>30}")
    print("  " + "─" * 74)
    for kind in LINES:
        ent, lines = {}, {}
        for s, d in frames.items():
            e, fast, slow = entries(d, kind)
            ent[s] = e
            lines[s] = slow
        tot = sum(len(v) for v in ent.values())
        a = st_(sim(frames, ent, lines, 0, mid))
        b = st_(sim(frames, ent, lines, mid, n0))
        ok = a and b and a["mean"] > 0 and b["mean"] > 0
        print(f"  {kind:<14}{f_(a):>30}{f_(b):>30}{'  ★양쪽+' if ok else ''}   (신호 {tot}건)")
    print("  " + "─" * 74)
    print("  참고: 라인 없이 신호 수식만 쓰면 봉인 −0.215 / 개발 −0.265 였다(−4.0σ/−4.6σ).")


if __name__ == "__main__":
    main()
