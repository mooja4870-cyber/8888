#!/usr/bin/env python3
"""verify_loss_side_8408.py — 손실 쪽 격자를 8408 전략(이중볼린저)으로 재검증

8403(MFI)에서 '손절폭 ×1.5 + 트레일 K=4.0'이 두 구간 모두 크게 개선됐다
(봉인 +15.5%→+31.2%, 개발 +12.9%→+19.2%).
전략을 바꿔도 성립하는지 확인한다. 한 전략에서만 통하면 그 전략의 특성일 뿐이다.

8408은 손절 산출 방식이 다르다(이중볼린저는 ATR 배수 기반). 그래서 같은 결론이
나오면 '손절을 조이면 손해'가 전략과 무관한 구조적 성질이라는 근거가 된다.
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = "/Users/l/project/8408"
CACHE = "/Users/l/project/8888/lab_cache_180"
SIGCACHE = "/Users/l/project/8888/lab/_sigcache_8408_180d.json"
WARMUP = 800
FEE = 0.001
MAX_POS = 3
sys.path.insert(0, BOT)
os.chdir(BOT)


def load():
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/binance_15m_*.json")):
        df = pd.DataFrame(json.load(open(p)), columns=["ts","open","high","low","close","volume"])
        c, h, l = df["close"], df["high"], df["low"]; pc = c.shift(1)
        tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=14, adjust=False).mean()
        out[os.path.basename(p).split("15m_")[1].split("_USDT")[0]] = df
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
    for s, df in frames.items():
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
        print(f"    {s:<9} {len(sg)}건", flush=True)
    json.dump(out, open(SIGCACHE, "w"))
    return out


def run_trade(df, s, direction, hold, sl_mult, k_ch, rr_mult):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values; n = len(df)
    i, e, risk0, rr0 = s["i"], s["e"], s["risk"], s["rr"]
    risk, rr = risk0 * sl_mult, rr0 * rr_mult
    long = direction == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak = e; end = min(n - 1, i + hold)
    j, done, out = i, False, 0.0
    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e) / e if long else (e - lo) / e
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


def simulate(frames, sigs, gates, lo, hi, sl_mult, k_ch, rr_mult, hold=24):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        d = s["dir"]
        if (gates[sym][i-1] > 0) != (d == "long"):
            continue
        ei, p = run_trade(frames[sym], s, d, hold, sl_mult, k_ch, rr_mult)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
    return pnl


def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    sigs = get_signals(frames)
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 48), 1, -1)
             for s, d in frames.items()}

    def run(sl, k, rr):
        cells, nets = [], []
        for a, b in ((0, mid), (mid, n0)):
            p = simulate(frames, sigs, gates, a, b, sl, k, rr)
            net = sum(p) * 100
            nets.append(net)
            wr = 100*sum(1 for x in p if x > 0)/len(p) if p else 0
            cells.append(f"{len(p)}건 {wr:.0f}% {net:+.1f}%")
        return cells, nets

    bc, base = run(1.0, 3.0, 1.0)
    print("  " + "═"*74)
    print(f"  {'설정':<30}{'봉인 앞90일(하락)':>22}{'개발 뒤90일(상승)':>22}")
    print("  " + "─"*74)
    print(f"  {'현행 (SL×1.0 K=3.0)':<30}{bc[0]:>22}{bc[1]:>22}")
    print("  " + "─"*74)
    for nm, sl, k, rr in (("손절폭 ×0.7", .7, 3., 1.), ("손절폭 ×1.5", 1.5, 3., 1.),
                          ("손절폭 ×2.0", 2., 3., 1.), ("트레일 K=2.0", 1., 2., 1.),
                          ("트레일 K=4.0", 1., 4., 1.), ("트레일 K=6.0", 1., 6., 1.),
                          ("K=4.0 + 손절 ×1.5", 1.5, 4., 1.),
                          ("K=4.0 + 손절 ×2.0", 2., 4., 1.)):
        cells, nets = run(sl, k, rr)
        ok = nets[0] > base[0] and nets[1] > base[1]
        print(f"  {nm:<30}{cells[0]:>22}{cells[1]:>22}{'  ✅' if ok else ''}")
    print("  " + "─"*74)


if __name__ == "__main__":
    main()
