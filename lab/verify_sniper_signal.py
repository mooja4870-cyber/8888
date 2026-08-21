#!/usr/bin/env python3
"""verify_sniper_signal.py — '15분봉 세력 흔적' 신호 수식 + 시간대 효과 검증

문서 출처
────────
`T 복사본 1/15분봉_세력_흔적_찾기_단타_매매_기법_가이드.pdf` (키움 영웅문 HTS 기준)

문서의 세 요소 중 **신호 수식만 완전히 명세**돼 있다. 세력라인·마지노선은
"승수 1.9 / 1.96"만 있고 원식이 없어 그대로 옮길 수 없다. 그래서 여기서는
신호 수식 자체에 엣지가 있는지부터 가린다. **없으면 두 선을 복원해도 소용없다.**

신호 수식 (문서 4페이지 원문 그대로)
    X1 = C > Highest(C, 15)            현재 종가 > 최근 15봉 최고 종가
    X2 = C(1) < Highest(C, 15, 1)      직전 봉은 미돌파 (첫 돌파)
    X3 = C > O                          양봉
    X4 = V > eavg(V, 20)                거래량 > 20봉 지수이평
    X5 = C > (Highest(H,15)+Lowest(L,15))/2   15봉 중심값 상회

시간대
────
문서는 "오전 9~10시에 수급 70% 집중"을 핵심 우위로 든다. 크립토는 24시간이라
그 시간대가 없다. mooja 지시로 **그래도 시간대별로 나눠 본다** —
크립토에도 아시아/유럽/미국 장 시작, 펀딩 정산(0·8·16 UTC) 같은 주기가 있다.

**주의**: 24개 시간대 중 최고를 고르면 24번 시험한 것이고, 엣지가 0이어도
좋아 보이는 게 반드시 나온다. 그래서 **앞절반에서 좋은 시간대가 뒤절반에서도
좋은지**를 본다. 한쪽에서만 좋으면 우연이다.
"""
import glob, json, os, sys, time
import numpy as np, pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_live"
FEE, SLIP, MAX_POS = 0.001, 0.0002, 3
N_BREAK, N_VOL = 15, 20


def load():
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/okx_15m_*.json")):
        s = os.path.basename(p).replace("okx_15m_", "").replace(".json", "")
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        c, h, l = df["close"], df["high"], df["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=14, adjust=False).mean()
        # 한국시간(UTC+9) 기준 시각 — 문서가 KST 기준이므로 맞춘다
        df["_hour"] = ((df["ts"] // 3600000) + 9) % 24
        out[s] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def signals(df):
    """X1~X5를 문서 그대로 적용. 완성봉 기준이며 진입은 다음 봉 시가."""
    c, o, h, l, v = (df["close"].values, df["open"].values, df["high"].values,
                     df["low"].values, df["volume"].values)
    cs = pd.Series(c)
    hi_c = cs.rolling(N_BREAK).max().shift(1).values          # Highest(C,15) — 직전까지
    hi_c_prev = cs.rolling(N_BREAK).max().shift(2).values     # Highest(C,15,1)
    hi_h = pd.Series(h).rolling(N_BREAK).max().shift(1).values
    lo_l = pd.Series(l).rolling(N_BREAK).min().shift(1).values
    vema = pd.Series(v).ewm(span=N_VOL, adjust=False).mean().values

    out = []
    for t in range(N_BREAK + N_VOL + 2, len(c) - 1):
        if not np.isfinite(hi_c[t]) or not np.isfinite(hi_c_prev[t]):
            continue
        x1 = c[t] > hi_c[t]
        x2 = c[t - 1] < hi_c_prev[t]
        x3 = c[t] > o[t]
        x4 = v[t] > vema[t]
        x5 = c[t] > (hi_h[t] + lo_l[t]) / 2.0
        if x1 and x2 and x3 and x4 and x5:
            out.append((t, int(df["_hour"].values[t])))
    return out


def run_trade(df, t, sl_atr, tp_pct, hold):
    o, h, l, c = (df["open"].values, df["high"].values,
                  df["low"].values, df["close"].values)
    atr = df["_atr"].values
    n = len(c)
    i = t + 1
    if i >= n:
        return i, None
    e = o[i] * (1 + SLIP)
    a0 = atr[t]
    if not np.isfinite(a0) or a0 <= 0 or e <= 0:
        return i, None
    risk = sl_atr * a0 / e
    if risk <= 0 or risk > 0.30:
        return i, None
    sl = e * (1 - risk)
    end, j, out = min(n - 1, i + hold), i, None
    while j <= end:
        if l[j] <= sl:
            out = -risk
            break
        if tp_pct and (h[j] - e) / e >= tp_pct:
            out = tp_pct
            break
        j += 1
    if out is None:
        out = (c[min(j, end)] - e) / e
    return min(j, end), out - FEE - SLIP


def sim(frames, sigs, lo, hi, sl_atr, tp_pct, hold, hours=None):
    allsig = sorted(((t, s, hh) for s, v in sigs.items() for t, hh in v
                     if lo <= t < hi and (hours is None or hh in hours)),
                    key=lambda x: x[0])
    busy, openp, pnl = {}, [], []
    for t, sym, _ in allsig:
        openp = [x for x in openp if x > t]
        if busy.get(sym, -1) >= t or len(openp) >= MAX_POS:
            continue
        ei, p = run_trade(frames[sym], t, sl_atr, tp_pct, hold)
        if p is None:
            continue
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def st_(p, minn=20):
    if len(p) < minn:
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
    sigs = {s: signals(d) for s, d in frames.items()}
    tot = sum(len(v) for v in sigs.values())
    print(f"  {len(frames)}종목 · {n0}봉(15분) = 180일 · 신호 {tot}건")
    print("  진입=다음 봉 시가 · 롱 전용(문서가 매수만 다룸) · 시각은 한국시간")

    print("\n  ■ 1) 신호 수식 자체 (시간대 무관)")
    print(f"    {'손절/익절/보유':<20}{'봉인 앞90일':>30}{'개발 뒤90일':>30}")
    best = None
    for sl_atr, tp, hold in ((1.5, 0.05, 24), (2.0, 0.05, 24), (2.0, 0.10, 48),
                             (3.0, 0.10, 48), (2.0, None, 24)):
        a = st_(sim(frames, sigs, 0, mid, sl_atr, tp, hold))
        b = st_(sim(frames, sigs, mid, n0, sl_atr, tp, hold))
        lab = f"ATR{sl_atr} / {'없음' if tp is None else f'{tp*100:.0f}%'} / {hold}봉"
        ok = a and b and a["mean"] > 0 and b["mean"] > 0
        print(f"    {lab:<20}{f_(a):>30}{f_(b):>30}{'  ★' if ok else ''}")
        if ok and (best is None or a["mean"] + b["mean"] > best[0]):
            best = (a["mean"] + b["mean"], sl_atr, tp, hold)

    sl_atr, tp, hold = (best[1], best[2], best[3]) if best else (2.0, 0.05, 24)
    print(f"\n  ■ 2) 시간대별 (한국시간) · 설정 ATR{sl_atr}/{tp}/{hold}봉")
    print("    24개 시간대를 다 보면 우연히 좋은 게 나온다. **양쪽 구간 모두** 좋아야 한다.")
    print(f"    {'시각(KST)':<12}{'봉인 앞90일':>30}{'개발 뒤90일':>30}")
    good = []
    for hh in range(24):
        a = st_(sim(frames, sigs, 0, mid, sl_atr, tp, hold, {hh}), minn=15)
        b = st_(sim(frames, sigs, mid, n0, sl_atr, tp, hold, {hh}), minn=15)
        ok = a and b and a["mean"] > 0 and b["mean"] > 0
        if ok:
            good.append(hh)
        if a or b:
            print(f"    {hh:02d}시{'':<8}{f_(a):>30}{f_(b):>30}{'  ★양쪽+' if ok else ''}")
    print(f"\n    양쪽 구간 플러스인 시간대: {good if good else '없음'}")

    if good:
        print(f"\n  ■ 3) 그 시간대만 모아서")
        a = st_(sim(frames, sigs, 0, mid, sl_atr, tp, hold, set(good)))
        b = st_(sim(frames, sigs, mid, n0, sl_atr, tp, hold, set(good)))
        print(f"    {str(good):<20}{f_(a):>30}{f_(b):>30}")
        print("    ※ 시간대를 성적으로 골랐으므로 이 수치는 낙관 쪽으로 치우친다.")


if __name__ == "__main__":
    main()
