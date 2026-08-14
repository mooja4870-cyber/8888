#!/usr/bin/env python3
"""verify_loss_1h.py — 1시간봉에서 손절폭·트레일링 K 재검증

15분봉 검증에서 나온 결론:
  · 트레일링 K=4.0 — 두 전략 모두 개선 (채택함)
  · 손절폭 — 8403은 넓혀야, 8408은 좁혀야 좋음 (전략 고유, 채택 보류)

그런데 8401·8409는 **1시간봉**이다. 봉 길이가 4배면 한 봉의 변동폭도 커지므로
같은 배수의 손절이 전혀 다른 의미를 갖는다. 15분봉 결론을 그대로 옮길 수 없다.

여기서는 8408 전략(이중볼린저)의 1시간봉 신호로 같은 격자를 돌린다.
캐시(_sigcache_8408_1h_180d.json)가 있어 재수집 없이 바로 비교 가능하다.
보유 한도는 24봉 등가(1시간봉 24시간).
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = "/Users/l/project/8408"
SIGCACHE = "/Users/l/project/8888/lab/_sigcache_8408_1h_180d.json"
FEE = 0.001
MAX_POS = 3
HOLD = 24                 # 1시간봉 24봉
sys.path.insert(0, BOT)
os.chdir(BOT)


def load(syms):
    out = {}
    for p in sorted(glob.glob("/Users/l/project/8888/lab_cache_tf/1h_*.json")):
        s = os.path.basename(p).split("1h_")[1].split("_USDT")[0]
        if s not in syms:
            continue
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts","open","high","low","close","volume"])
        df = df.iloc[-(180*24):].reset_index(drop=True)      # 180일치
        c, h, l = df["close"], df["high"], df["low"]; pc = c.shift(1)
        tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=14, adjust=False).mean()
        out[s] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def run_trade(df, s, direction, sl_mult, k_ch):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values; n = len(df)
    i, e, risk0, rr = s["i"], s["e"], s["risk"], s["rr"]
    risk = risk0 * sl_mult
    long = direction == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak = e; end = min(n - 1, i + HOLD)
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


def simulate(frames, sigs, gates, lo, hi, sl_mult, k_ch):
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
        ei, p = run_trade(frames[sym], s, d, sl_mult, k_ch)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
    return pnl


def main():
    sigs = json.load(open(SIGCACHE))
    frames = load(set(sigs))
    sigs = {k: v for k, v in sigs.items() if k in frames}
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 12), 1, -1)   # 1h 12봉=12시간
             for s, d in frames.items()}

    def run(sl, k):
        cells, nets = [], []
        for a, b in ((0, mid), (mid, n0)):
            p = simulate(frames, sigs, gates, a, b, sl, k)
            net = sum(p) * 100
            nets.append(net)
            wr = 100*sum(1 for x in p if x > 0)/len(p) if p else 0
            cells.append(f"{len(p)}건 {wr:.0f}% {net:+.1f}%")
        return cells, nets

    print(f"  1시간봉 · {len(frames)}종목 · {n0}봉 = {n0/24:.0f}일 · 게이트EMA 12")
    bc, base = run(1.0, 4.0)            # 기준선은 이미 채택한 K=4.0
    print("  " + "═"*72)
    print(f"  {'설정':<28}{'봉인 앞90일(하락)':>22}{'개발 뒤90일(상승)':>22}")
    print("  " + "─"*72)
    print(f"  {'기준 (SL×1.0 K=4.0)':<28}{bc[0]:>22}{bc[1]:>22}")
    print("  " + "─"*72)
    tests = [(f"트레일 K={k}", 1.0, k) for k in (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0)]
    tests += [(f"K=3.0 + 손절 ×{sl}", sl, 3.0) for sl in (0.5, 0.7, 1.5)]
    tests += [(f"K=2.5 + 손절 ×{sl}", sl, 2.5) for sl in (0.7, 1.0)]
    for nm, sl, k in tests:
        cells, nets = run(sl, k)
        ok = nets[0] > base[0] and nets[1] > base[1]
        print(f"  {nm:<28}{cells[0]:>22}{cells[1]:>22}{'  ✅' if ok else ''}")
    print("  " + "─"*72)


if __name__ == "__main__":
    main()
