#!/usr/bin/env python3
"""verify_tf_exit_scaling.py — 청산 기준은 '봉 수'로 맞춰야 하나 '시간'으로 맞춰야 하나

mooja 지적
─────────
타임프레임이 15분봉·1시간봉 둘인데 청산 기준이 거의 같다. 이상하지 않은가.

확인해 보니 실제로 **두 기준이 서로 모순**돼 있었다.
  · 최대보유  24봉 / 24봉  → **봉 수**를 같게 (6시간 vs 24시간)
  · 게이트EMA 48봉 / 12봉  → **시간**을 같게 (둘 다 12시간)
왜 하나는 봉 기준이고 하나는 시간 기준인지 근거가 없다. 24봉은 검증해서 고른
값이 아니라 물려받은 값이다.

그래서 **같은 종목·같은 기간**에서 두 타임프레임을 나란히 놓고 최적값을 각각 찾는다.
15분봉 원자료를 1시간봉으로 합치므로 종목·기간·전략이 완전히 동일하다.
차이가 나면 그건 타임프레임 때문이지 표본 때문이 아니다.

묻는 것
  1. 최대보유의 최적값이 두 TF에서 **같은 봉 수**인가, **같은 시간**인가
  2. 샹들리에 K의 최적값이 ATR 비율대로 갈리는가 (현행 15m=4.0 / 1h=2.0)
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = "/Users/l/project/8403"
CACHE = "/Users/l/project/8888/lab_cache_live"
SIG15 = "/Users/l/project/8888/lab/_sigcache_8403_live61.json"
SIG1H = "/Users/l/project/8888/lab/_sigcache_8403_live61_1h.json"
WARMUP, FEE, MAX_POS = 800, 0.001, 3

sys.path.insert(0, BOT)


def _atr(df):
    c, h, l = df["close"], df["high"], df["low"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["_atr"] = tr.ewm(span=14, adjust=False).mean()
    return df


def load(tf):
    """tf: '15m' | '1h'. 1h는 15분봉 4개를 합쳐 만든다(같은 원자료 보장)."""
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/okx_15m_*.json")):
        s = os.path.basename(p).replace("okx_15m_", "").replace(".json", "")
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        if tf == "1h":
            n = len(df) // 4 * 4
            df = df.iloc[len(df) - n:].reset_index(drop=True)
            g = df.groupby(df.index // 4)
            df = pd.DataFrame({
                "ts": g["ts"].first(), "open": g["open"].first(),
                "high": g["high"].max(), "low": g["low"].min(),
                "close": g["close"].last(), "volume": g["volume"].sum(),
            }).reset_index(drop=True)
        out[s] = _atr(df)
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def get_signals(frames, cache):
    if os.path.exists(cache):
        d = json.load(open(cache))
        if set(d) == set(frames):
            print(f"    신호 캐시 재사용 ({os.path.basename(cache)})", flush=True)
            return d
    cwd = os.getcwd()
    os.chdir(BOT)
    from core.strategy import StrategyEngine
    st = StrategyEngine()
    out = {}
    for n, (s, df) in enumerate(frames.items(), 1):
        sg = []
        for i in range(WARMUP, len(df) - 1):
            g = st.generate_signal(df.iloc[i - WARMUP:i], s)
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
        if n % 20 == 0:
            print(f"      [{n}/{len(frames)}] 누적 {sum(len(v) for v in out.values())}건", flush=True)
    os.chdir(cwd)
    json.dump(out, open(cache, "w"))
    return out


def run_trade(df, s, k_ch, hold):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(c)
    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = s["dir"] == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak, end, j = e, min(n - 1, i + hold), s["i"]
    while j <= end:
        gain = (h[j] - e) / e if long else (e - l[j]) / e
        if (long and l[j] <= sl) or (not long and h[j] >= sl):
            return j, ((sl - e) / e if long else (e - sl) / e) - FEE
        if gain >= tp_pct:
            return j, tp_pct - FEE
        peak = max(peak, h[j]) if long else min(peak, l[j])
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k_ch * a) if long else (peak + k_ch * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    last = c[min(j, end)]
    return min(j, end), ((last - e) / e if long else (e - last) / e) - FEE


def simulate(frames, sigs, gates, lo, hi, k_ch, hold):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        if (gates[sym][i - 1] > 0) != (s["dir"] == "long"):
            continue
        ei, p = run_trade(frames[sym], s, k_ch, hold)
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def tot(p):
    return sum(p) * 100 if p else 0.0


def main():
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    for tf, cache, gate_bars, cur_k, bar_min in (("15m", SIG15, 48, 4.0, 15),
                                                 ("1h", SIG1H, 12, 2.0, 60)):
        print(f"\n{'═'*84}\n  ■ {tf} — 게이트EMA {gate_bars}봉(=12시간) 고정", flush=True)
        frames = load(tf)
        n0 = len(next(iter(frames.values())))
        mid = n0 // 2
        print(f"    {len(frames)}종목 · {n0}봉 = {n0*bar_min/60/24:.0f}일", flush=True)
        sigs = get_signals(frames, cache)
        print(f"    신호 {sum(len(v) for v in sigs.values())}건", flush=True)
        gates = {s: np.where(d["close"].values > ema(d["close"].values, gate_bars), 1, -1)
                 for s, d in frames.items()}

        holds = [6, 12, 24, 48, 96] if tf == "15m" else [6, 12, 24, 48]
        print(f"\n    ── 최대보유 격자 (K={cur_k} 고정) ──")
        print(f"    {'보유':<18}{'봉인 앞90일':>20}{'개발 뒤90일':>20}{'합':>10}")
        for hd in holds:
            a = tot(simulate(frames, sigs, gates, 0, mid, cur_k, hd))
            b = tot(simulate(frames, sigs, gates, mid, n0, cur_k, hd))
            lab = f"{hd}봉 ({hd*bar_min/60:.0f}시간)"
            mark = "  ← 현행" if hd == 24 else ""
            print(f"    {lab:<18}{a:>19.1f}%{b:>19.1f}%{a+b:>9.1f}%{mark}")

        print(f"\n    ── 샹들리에 K 격자 (보유 24봉 고정) ──")
        print(f"    {'K':<18}{'봉인 앞90일':>20}{'개발 뒤90일':>20}{'합':>10}")
        for k in (1.5, 2.0, 3.0, 4.0, 6.0):
            a = tot(simulate(frames, sigs, gates, 0, mid, k, 24))
            b = tot(simulate(frames, sigs, gates, mid, n0, k, 24))
            mark = "  ← 현행" if abs(k - cur_k) < 1e-9 else ""
            print(f"    K={k:<16.1f}{a:>19.1f}%{b:>19.1f}%{a+b:>9.1f}%{mark}")


if __name__ == "__main__":
    main()
