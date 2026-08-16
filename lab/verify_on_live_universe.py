#!/usr/bin/env python3
"""verify_on_live_universe.py — 실거래와 같은 종목군으로 핵심 검증 재실행

왜 다시 하는가
─────────────
지금까지 검증은 거래대금 상위 15종목으로 했는데, 실거래는 45종목에서 이뤄졌고
겹치는 건 6개(13%)뿐이었다. 실거래의 80%가 거래대금 $3M 미만 종목이고
손실의 86%가 거기서 나왔다. **대형주로 검증하고 소형주로 매매한 것이다.**

여기서는 실거래와 같은 조건(≥$500K 상위 80 → 실제 확보 61종목)의 180일
15분봉으로 이번 주 결론들을 다시 확인한다. 종목군이 바뀌어도 같은 결론이면
그 원리는 튼튼하고, 뒤집히면 이번 주 결론을 재검토해야 한다.

확인 대상 (조기청산 계열 중 재현 가능한 것)
  · 방향 게이트 ON/OFF
  · 샹들리에 K (2.0 / 3.0 / 4.0 / 6.0)
  · 동적청산 유무는 지표 재계산이 필요해 제외 — K 검증으로 대리한다
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = "/Users/l/project/8403"
CACHE = "/Users/l/project/8888/lab_cache_live"
SIGCACHE = "/Users/l/project/8888/lab/_sigcache_8403_live61.json"
WARMUP = 800
FEE = 0.001
MAX_POS = 3
sys.path.insert(0, BOT)
os.chdir(BOT)


def load():
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/okx_15m_*.json")):
        s = os.path.basename(p).replace("okx_15m_", "").replace(".json", "")
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts","open","high","low","close","volume"])
        c, h, l = df["close"], df["high"], df["low"]; pc = c.shift(1)
        tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=14, adjust=False).mean()
        out[s] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def get_signals(frames):
    if os.path.exists(SIGCACHE):
        d = json.load(open(SIGCACHE))
        if set(d) == set(frames):
            print("  신호 캐시 재사용", flush=True)
            return d
    from core.strategy import StrategyEngine
    st = StrategyEngine()
    out = {}
    for n, (s, df) in enumerate(frames.items(), 1):
        sg = []
        for i in range(WARMUP, len(df) - 1):
            g = st.generate_signal(df.iloc[i-WARMUP:i], s)
            if g.direction == "none":
                continue
            e, sl, tp = g.close, g.swing_sl_price, g.tp1_price
            if not (e > 0 and sl > 0 and tp > 0):
                continue
            risk = abs(e - sl) / e
            if risk <= 0:
                continue
            sg.append({"i": i, "dir": g.direction, "e": e, "risk": risk,
                       "rr": abs(tp - e) / e / risk})
        out[s] = sg
        if n % 10 == 0:
            print(f"    [{n}/{len(frames)}] 누적 {sum(len(v) for v in out.values())}건", flush=True)
    json.dump(out, open(SIGCACHE, "w"))
    return out


def run_trade(df, s, direction, k_ch, hold=24):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values; n = len(df)
    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = direction == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak = e; end = min(n - 1, i + hold)
    j, done, out = i, False, 0.0
    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e)/e if long else (e - lo)/e
        if (long and lo <= sl) or (not long and hi >= sl):
            out = (sl - e)/e if long else (e - sl)/e; done = True; break
        if gain >= tp_pct:
            out = tp_pct; done = True; break
        peak = max(peak, hi) if long else min(peak, lo)
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k_ch*a) if long else (peak + k_ch*a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if not done:
        last = c[min(j, end)]
        out = (last - e)/e if long else (e - last)/e
    return min(j, end), out - FEE


def simulate(frames, sigs, gates, lo, hi, k_ch, use_gate):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        d = s["dir"]
        if use_gate and (gates[sym][i-1] > 0) != (d == "long"):
            continue
        ei, p = run_trade(frames[sym], s, d, k_ch)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
    return pnl


def fmt(p):
    if not p:
        return "0건"
    w = sum(1 for x in p if x > 0)
    return f"{len(p)}건 {100*w/len(p):.0f}% {sum(p)*100:+.1f}%"


def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    print(f"  {len(frames)}종목 · {n0}봉 = {n0*15/60/24:.0f}일 (실거래와 같은 종목군)")
    sigs = get_signals(frames)
    tot = sum(len(v) for v in sigs.values())
    print(f"  신호 총 {tot}건")
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 48), 1, -1)
             for s, d in frames.items()}
    print("  " + "═"*70)
    print(f"  {'설정':<26}{'봉인 앞90일':>21}{'개발 뒤90일':>21}")
    print("  " + "─"*70)
    for nm, k, gt in (("게이트 없음 · K=4.0", 4.0, False),
                      ("게이트 ON · K=2.0", 2.0, True),
                      ("게이트 ON · K=3.0", 3.0, True),
                      ("게이트 ON · K=4.0 (현행)", 4.0, True),
                      ("게이트 ON · K=6.0", 6.0, True)):
        cells = [fmt(simulate(frames, sigs, gates, a, b, k, gt))
                 for a, b in ((0, mid), (mid, n0))]
        print(f"  {nm:<26}{cells[0]:>21}{cells[1]:>21}")
    print("  " + "─"*70)


if __name__ == "__main__":
    main()
