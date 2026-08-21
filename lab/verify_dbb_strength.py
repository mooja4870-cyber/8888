#!/usr/bin/env python3
"""verify_dbb_strength.py — 8408 신호 신뢰도(⑧)와 추세강도 필터(⑥) 임계값 검증

경위
────
mooja 지시로 두 기법을 8408에 적용했다. 적용 과정에서 결함을 하나 찾았다.

**⑧ 신호 신뢰도** — 실측 541건이 **전부 강도 100%**였다. 원인은 감점 조건 두 개
(`rsi_ok` 미충족·스퀴즈)가 **이미 진입 조건으로 걸러진 뒤**라 발생할 수 없었기 때문이다.
즉 게이트 80은 아무것도 거르지 못하는 장식이었다. 연속값으로 다시 만들었다:
  깊이(밴드 이탈 ATR배수) 0.40 + RSI 극단도 0.30 + ADX 낮음 0.30 → 40~100

**⑥ 추세 강도** — `DBB_USE_ADX_FILTER`가 코드에 이미 있었고 꺼져 있었다. 켰다.
임계값 28은 검증한 값이 아니라 물려받은 값이다.

가중치와 임계값은 임의로 정하면 안 된다. 여기서 실제로 잰다.
  · 강도가 흩어지는가 (상수면 여전히 쓸모없다)
  · 강도가 높을수록 성적이 좋은가 (아니면 거를 이유가 없다)
  · ADX 임계값은 얼마가 맞는가

자료: 61종목 · 180일 · 15분봉(8408과 같은 주기) · 진입은 다음 봉 시가
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = "/Users/l/project/8408"
CACHE = "/Users/l/project/8888/lab_cache_live"
SIGCACHE = "/Users/l/project/8888/lab/_sigcache_8408_dbb.json"
WARMUP, FEE, SLIP, MAX_POS, HOLD = 800, 0.001, 0.0002, 3, 24


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
        out[s] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def gen(frames):
    """8408의 실제 전략으로 신호 생성. 강도·ADX를 함께 기록한다."""
    if os.path.exists(SIGCACHE):
        d = json.load(open(SIGCACHE))
        if set(d) == set(frames):
            print("    신호 캐시 재사용", flush=True)
            return d
    cwd = os.getcwd()
    sys.path.insert(0, BOT)
    os.chdir(BOT)
    from core.strategy import StrategyEngine
    st = StrategyEngine()
    st.cfg.DBB_USE_ADX_FILTER = False       # 검증에서 직접 거르려고 전략 단 필터는 끈다
    out = {}
    for n, (s, df) in enumerate(frames.items(), 1):
        sg = []
        for i in range(WARMUP, len(df) - 1):
            # i+1까지 넘긴다 → 전략이 마지막 봉을 잘라내고 i-1을 쓴다(실거래와 동일)
            g = st.generate_signal(df.iloc[i - WARMUP:i + 1], s)
            if g.direction == "none":
                continue
            e, sl, tp = g.close, g.swing_sl_price, g.tp1_price
            if not (e > 0 and sl > 0 and tp > 0):
                continue
            risk = abs(e - sl) / e
            if risk <= 0 or risk > 0.30:
                continue
            sg.append({"i": i, "dir": g.direction, "e": e, "risk": risk,
                       "rr": abs(tp - e) / e / risk,
                       "str": int(g.strength), "adx": float(g.adx or 0.0)})
        out[s] = sg
        if n % 20 == 0:
            print(f"      [{n}/{len(frames)}] 누적 {sum(len(v) for v in out.values())}건", flush=True)
    os.chdir(cwd)
    json.dump(out, open(SIGCACHE, "w"))
    return out


def run_trade(df, s):
    o, h, l, c = (df["open"].values, df["high"].values,
                  df["low"].values, df["close"].values)
    n = len(c)
    i = s["i"] + 1
    if i >= n:
        return i, None
    long = s["dir"] == "long"
    e = o[i] * (1 + SLIP) if long else o[i] * (1 - SLIP)
    if e <= 0:
        return i, None
    risk, rr = s["risk"], s["rr"]
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    end, j, out = min(n - 1, i + HOLD), i, None
    while j <= end:
        gain = (h[j] - e) / e if long else (e - l[j]) / e
        if (long and l[j] <= sl) or (not long and h[j] >= sl):
            out = -risk
            break
        if gain >= tp_pct:
            out = tp_pct
            break
        j += 1
    if out is None:
        out = (c[min(j, end)] - e) / e if long else (e - c[min(j, end)]) / e
    return min(j, end), out - FEE - SLIP


def sim(frames, sigs, lo, hi, min_str=0, max_adx=999):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        if s["str"] < min_str or s["adx"] > max_adx:
            continue
        ei, p = run_trade(frames[sym], s)
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
    print(f"  8408 이중볼린저 · {len(frames)}종목 · {n0}봉(15분) = 180일")
    sigs = gen(frames)
    allv = [x for v in sigs.values() for x in v]
    print(f"  신호 {len(allv)}건")

    strs = np.array([x["str"] for x in allv])
    adxs = np.array([x["adx"] for x in allv])
    print(f"\n  ■ ⑧ 강도가 흩어지는가 (종전엔 541건 전부 100이었다)")
    print(f"    최소 {strs.min()} · 25% {np.percentile(strs,25):.0f} · 중앙 {np.median(strs):.0f}"
          f" · 75% {np.percentile(strs,75):.0f} · 최대 {strs.max()} · 고유값 {len(set(strs))}개")
    print(f"    ADX  최소 {adxs.min():.0f} · 중앙 {np.median(adxs):.0f} · 최대 {adxs.max():.0f}")

    print(f"\n  ■ ⑧ 강도 하한별 성적")
    print(f"    {'하한':<8}{'봉인 앞90일':>30}{'개발 뒤90일':>30}")
    for ms in (0, 60, 70, 80, 85, 90):
        a, b = st_(sim(frames, sigs, 0, mid, min_str=ms)), st_(sim(frames, sigs, mid, n0, min_str=ms))
        mark = "  ← 현행 게이트" if ms == 80 else ""
        print(f"    {ms:<8}{f_(a):>30}{f_(b):>30}{mark}")

    print(f"\n  ■ ⑥ ADX 상한별 성적 (역추세는 추세장에서 밀린다)")
    print(f"    {'상한':<8}{'봉인 앞90일':>30}{'개발 뒤90일':>30}")
    for ma in (999, 35, 28, 22, 18):
        a, b = st_(sim(frames, sigs, 0, mid, max_adx=ma)), st_(sim(frames, sigs, mid, n0, max_adx=ma))
        mark = "  ← 현행 임계" if ma == 28 else ("  (필터 없음)" if ma == 999 else "")
        print(f"    {ma:<8}{f_(a):>30}{f_(b):>30}{mark}")

    print(f"\n  ■ 둘 다 적용")
    print(f"    {'강도/ADX':<12}{'봉인 앞90일':>30}{'개발 뒤90일':>30}")
    for ms, ma in ((70, 28), (80, 28), (80, 22), (85, 22)):
        a, b = st_(sim(frames, sigs, 0, mid, ms, ma)), st_(sim(frames, sigs, mid, n0, ms, ma))
        print(f"    {ms}/{ma:<8}{f_(a):>30}{f_(b):>30}")


if __name__ == "__main__":
    main()
