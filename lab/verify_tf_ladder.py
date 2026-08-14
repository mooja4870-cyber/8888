#!/usr/bin/env python3
"""verify_tf_ladder.py — 15분 / 1시간 / 4시간봉 사다리 비교

질문: "1시간봉이 15분봉보다 나았는데, 4시간봉으로 더 올리면 더 나은가?"

공정성 조치
──────────
* **공통 12종목**만 쓴다(4시간봉 캐시에 없는 BEAT·CYS·PUMP 제외).
* **같은 180일 구간**으로 잘라 쓴다. 캐시 기간이 15m 180일 / 1h 241~360일 /
  4h 720일로 달라서, 안 맞추면 서로 다른 시장을 비교하게 된다.
  (앞선 8409 검증은 이 보정을 안 해 1h가 유리했을 여지가 있다 — 한계로 기록했다)
* 봉 수 기준 설정을 등가 환산한다. 게이트 12시간 · 보유 24봉.
      15m → 게이트 48봉 · 보유 24봉(6시간)
      1h  → 게이트 12봉 · 보유 24봉(24시간)
      4h  → 게이트  3봉 · 보유 24봉(96시간)

청산 경로는 현행 실거래와 동일(분할익절·본전보호·횡보청산·긴급트레일 해제,
방향 게이트 ON, 손절 + 거래소 TP + 샹들리에 트레일링).
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = sys.argv[1] if len(sys.argv) > 1 else "/Users/l/project/8408"
FEE = 0.001
MAX_POS = 3
WARMUP = 800
DAYS = 180                     # 공통 구간
sys.path.insert(0, BOT)
os.chdir(BOT)

TFS = [("15m", 15, 48), ("1h", 60, 12), ("4h", 240, 3)]   # (이름, 분, 게이트봉수)


def common_symbols():
    def names(pat, cut):
        return {os.path.basename(p).split(cut)[1].split("_USDT")[0]
                for p in glob.glob(pat)}
    a = names("/Users/l/project/8888/lab_cache_180/binance_15m_*.json", "15m_")
    b = names("/Users/l/project/8888/lab_cache_tf/1h_*.json", "1h_")
    c = names("/Users/l/project/8888/lab_cache_tf/4h_*.json", "4h_")
    return sorted(a & b & c)


def load(tf, minutes, syms):
    pat = ("/Users/l/project/8888/lab_cache_180/binance_15m_*.json" if tf == "15m"
           else f"/Users/l/project/8888/lab_cache_tf/{tf}_*.json")
    cut = "15m_" if tf == "15m" else f"{tf}_"
    want = int(DAYS * 24 * 60 / minutes)          # 180일치 봉 수
    out = {}
    for p in sorted(glob.glob(pat)):
        s = os.path.basename(p).split(cut)[1].split("_USDT")[0]
        if s not in syms:
            continue
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        df = df.iloc[-want:].reset_index(drop=True)
        c, h, l = df["close"], df["high"], df["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=14, adjust=False).mean()
        out[s] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def get_signals(frames, tf, tag):
    cache = f"/Users/l/project/8888/lab/_sigcache_{tag}_{tf}_{DAYS}d.json"
    if os.path.exists(cache):
        d = json.load(open(cache))
        if set(d) == set(frames):
            print(f"    [{tf}] 캐시 재사용", flush=True)
            return d
    from core.strategy import StrategyEngine
    st = StrategyEngine()
    out = {}
    for s, df in frames.items():
        sg = []
        for i in range(min(WARMUP, len(df) // 3), len(df) - 1):
            g = st.generate_signal(df.iloc[max(0, i - WARMUP):i], s)
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
        print(f"    [{tf}] {s:<9} {len(sg)}건", flush=True)
    json.dump(out, open(cache, "w"))
    return out


def run_trade(df, s, direction, hold=24, k_ch=3.0):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = direction == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak = e
    end = min(n - 1, i + hold)
    j, done, out = i, False, 0.0
    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e) / e if long else (e - lo) / e
        if (long and lo <= sl) or (not long and hi >= sl):
            out = (sl - e) / e if long else (e - sl) / e
            done = True
            break
        if gain >= tp_pct:
            out = tp_pct
            done = True
            break
        peak = max(peak, hi) if long else min(peak, lo)
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k_ch * a) if long else (peak + k_ch * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if not done:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), out - FEE


def simulate(frames, sigs, gates, lo, hi):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        d = s["dir"]
        if (gates[sym][i - 1] > 0) != (d == "long"):
            continue
        ei, p = run_trade(frames[sym], s, d)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
    return pnl


def main():
    tag = os.path.basename(BOT)
    syms = common_symbols()
    ema = lambda a, sp: pd.Series(a).ewm(span=sp, adjust=False).mean().values
    print(f"  전략={tag} · 공통 {len(syms)}종목 · 같은 {DAYS}일 구간")
    print("  " + "═" * 74)
    print(f"  {'타임프레임':<14}{'봉인 앞90일(하락)':>27}{'개발 뒤90일(상승)':>27}")
    print("  " + "─" * 74)
    for tf, minutes, gspan in TFS:
        frames = load(tf, minutes, syms)
        n0 = len(next(iter(frames.values()))); mid = n0 // 2
        sigs = get_signals(frames, tf, tag)
        gates = {s: np.where(d["close"].values > ema(d["close"].values, gspan), 1, -1)
                 for s, d in frames.items()}
        cells = []
        for a, b in ((0, mid), (mid, n0)):
            p = simulate(frames, sigs, gates, a, b)
            net = sum(p) * 100
            wr = 100 * sum(1 for x in p if x > 0) / len(p) if p else 0
            cells.append(f"{len(p)}건 {wr:.0f}% {net:+.1f}%")
        print(f"  {tf:<14}{cells[0]:>27}{cells[1]:>27}")
    print("  " + "─" * 74)


if __name__ == "__main__":
    main()
