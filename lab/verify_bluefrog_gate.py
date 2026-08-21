#!/usr/bin/env python3
"""verify_bluefrog_gate.py — 8408 전략에서 역매매 × 게이트 4조합 검증

경위
────
8408·8409는 신호 106·103건이 **전부** 게이트에 막혀 진입 0건이 됐다.
원인은 내가 두 조치를 겹친 것이다.

  * 이 봇들의 전략(이중볼린저 역추세 되돌림)은 원래 **역매매 ON** 전제로 운영됐다.
    역매매가 켜져 있으면 신호가 뒤집혀 결과적으로 추세 순응 방향이 된다.
  * 내가 역매매를 끄자 신호가 본래의 역추세 방향으로 나갔고,
    추세 순응을 요구하는 게이트와 100% 충돌했다.

두 조치의 상호작용을 검증하지 않고 함께 적용한 것이 잘못이다. 여기서 4조합을
국면이 정반대인 두 구간에서 비교해 근거를 만든다.

  ① 역매매 ON  + 게이트 OFF   (8/8 이전 원래 운영방식)
  ② 역매매 ON  + 게이트 ON
  ③ 역매매 OFF + 게이트 OFF
  ④ 역매매 OFF + 게이트 ON    (현재 — 진입 0건)

두 구간 모두에서 가장 나은 조합만 채택한다. 엇갈리면 국면 의존이므로 기각한다.
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = "/Users/l/project/8408"
CACHE = "/Users/l/project/8888/lab_cache_180"
SIGCACHE = "/Users/l/project/8888/lab/_sigcache_8408_180d.json"
WARMUP = 800
FEE = 0.001
MAX_POS = 3
sys.path.insert(0, BOT); os.chdir(BOT)
sys.path.insert(0, "/Users/l/project/8888")


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
        print(f"    {s:<8} 신호 {len(sg)}건", flush=True)
    json.dump(out, open(SIGCACHE, "w"))
    return out


def run_trade(df, s, direction, cfg):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values; n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    pt_on = bool(cfg.get("USE_PARTIAL_TP", True))
    pt_trig, pt_frac = g("PARTIAL_TP_TRIGGER_PCT", .015), g("PARTIAL_TP_FRACTION", .5)
    k_ch = g("CHANDELIER_K", 3.0)
    hold = int(g("MAX_HOLDING_HOURS", 6.0) * 4) or 10**9
    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = direction == "long"
    sl = e * (1 - risk) if long else e * (1 + risk)
    tp = e * (1 + risk * rr) if long else e * (1 - risk * rr)
    realized, remain = 0.0, 1.0
    part, trail, peak = False, False, e
    end = min(n - 1, i + hold); j, done = i, False
    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e) / e if long else (e - lo) / e
        if pt_on and not part and gain >= pt_trig:
            realized += pt_frac * pt_trig; remain -= pt_frac
            part, trail, peak = True, True, (hi if long else lo)
        if trail:
            peak = max(peak, hi) if long else min(peak, lo)
            a = atr[j] if atr[j] == atr[j] else 0.0
            ch = (peak - k_ch * a) if long else (peak + k_ch * a)
            sl = max(sl, ch) if long else min(sl, ch)
        if (long and lo <= sl) or (not long and hi >= sl):
            realized += remain * ((sl - e)/e if long else (e - sl)/e); done = True; break
        if not part and ((long and hi >= tp) or (not long and lo <= tp)):
            realized += remain * (risk * rr); done = True; break
        j += 1
    if not done:
        last = c[min(j, end)]
        realized += remain * ((last - e)/e if long else (e - last)/e)
    return min(j, end), realized - FEE


def simulate(frames, sigs, gates, cfg, lo, hi, bluefrog, use_gate):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        d = s["dir"]
        if bluefrog:
            d = "short" if d == "long" else "long"
        if use_gate and (gates[sym][i-1] > 0) != (d == "long"):
            continue
        ei, p = run_trade(frames[sym], s, d, cfg)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
    return pnl


def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    sigs = get_signals(frames)
    cfg = dict(json.load(open(f"{BOT}/config.json")))
    cfg["USE_BE_GUARD"] = False
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 48), 1, -1)
             for s, d in frames.items()}

    print("  " + "═" * 76)
    print(f"  {'조합':<32}{'봉인 앞90일(하락)':>22}{'개발 뒤90일(상승)':>22}")
    print("  " + "─" * 76)
    res = {}
    combos = [("① 역매매 ON  + 게이트 OFF (원래)", True,  False),
              ("② 역매매 ON  + 게이트 ON",         True,  True),
              ("③ 역매매 OFF + 게이트 OFF",        False, False),
              ("④ 역매매 OFF + 게이트 ON (현재)",  False, True)]
    for nm, bf, gt in combos:
        cells = []
        for tag, a, b in (("봉인", 0, mid), ("개발", mid, n0)):
            p = simulate(frames, sigs, gates, cfg, a, b, bf, gt)
            net = sum(p) * 100
            wr = 100 * sum(1 for x in p if x > 0) / len(p) if p else 0
            res[(nm, tag)] = net
            cells.append(f"{len(p)}건 {wr:.0f}% {net:+.1f}%")
        print(f"  {nm:<32}{cells[0]:>22}{cells[1]:>22}")
    print("  " + "─" * 76)
    both = [(nm, res[(nm,"봉인")], res[(nm,"개발")]) for nm,_,_ in combos]
    ok = [x for x in both if x[1] > 0 and x[2] > 0]
    if ok:
        best = max(ok, key=lambda x: min(x[1], x[2]))
        print(f"  두 구간 모두 양수: {', '.join(x[0].split('(')[0].strip() for x in ok)}")
        print(f"  → 최악구간이 가장 나은 조합: {best[0]}")
    else:
        print("  두 구간 모두 양수인 조합 없음 — 판정 보류")


if __name__ == "__main__":
    main()
