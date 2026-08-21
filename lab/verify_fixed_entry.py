#!/usr/bin/env python3
"""verify_fixed_entry.py — 진입가 결함을 고치고 핵심 결론을 전부 다시 잰다

무엇이 잘못됐나
──────────────
`core/strategy.py:191`이 미완성 봉을 하나 잘라낸다(`df_ind.iloc[:-1]`).
그런데 내 검증은 `df.iloc[i-WARMUP:i]`를 넘겼다. 마지막 봉이 이미 완성된 i-1인데
전략이 그걸 또 잘라서 **i-2의 종가**를 진입가로 썼다.

즉 백테스트는 **15분 전 가격에 산 것으로 계산**했다. 실거래는 그럴 수 없다.
실측: 신호 진입가와 다음 봉 시가의 절대중앙 차이가 **0.1748%**.
백테-실거래 괴리 −0.200%p와 크기가 맞는다.

이 전략은 역추세(MFI 다이버전스)다. 신호는 가격이 극단으로 간 자리에서 뜨고
다음 봉에 되돌아온다. 백테는 되돌림 **전**에 샀고 실거래는 **후**에 산다.
엣지 전부가 그 한 봉 안에 있었다.

무엇을 고쳤나
────────────
`df.iloc[i-WARMUP:i+1]`을 넘긴다. 전략이 마지막 봉(i)을 잘라내면 i-1이 남고,
진입가는 close[i-1] ≈ open[i]가 된다. 거래는 봉 i부터 굴린다.
**실거래와 같아진다** — 봇은 닫힌 봉 i-1을 보고 봉 i 시작 무렵 시장가로 들어간다.

무엇을 확인하나
──────────────
고친 진입가 위에서 이번 주 결론이 살아남는지. 특히
  · 방향 게이트 (−107% → +30%였던 그것)
  · 샹들리에 K
  · 최대보유
하나라도 뒤집히면 그 결론은 폐기다.
"""
import json, os, sys
import numpy as np, pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_tf_exit_scaling import load

BOT = "/Users/l/project/8403"
SIG_FIX = "/Users/l/project/8888/lab/_sigcache_8403_live61_fixed.json"
WARMUP, FEE, MAX_POS, GATE = 800, 0.001, 3, 48
SLIP = 0.0002          # 시장가 미끄러짐 진입·청산 각 0.02%


def get_signals(frames):
    """진입가를 고쳐 신호를 다시 만든다. e = close[i-1]."""
    if os.path.exists(SIG_FIX):
        d = json.load(open(SIG_FIX))
        if set(d) == set(frames):
            print("    신호 캐시 재사용 (고친 버전)", flush=True)
            return d
    cwd = os.getcwd()
    sys.path.insert(0, BOT)
    os.chdir(BOT)
    from core.strategy import StrategyEngine
    st = StrategyEngine()
    out = {}
    for n, (s, df) in enumerate(frames.items(), 1):
        sg = []
        c = df["close"].values
        for i in range(WARMUP, len(df) - 1):
            # i+1 까지 넘긴다 → 전략이 봉 i를 잘라내고 봉 i-1을 쓴다 (실거래와 동일)
            g = st.generate_signal(df.iloc[i - WARMUP:i + 1], s)
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
            print(f"      [{n}/{len(frames)}] 누적 {sum(len(v) for v in out.values())}건",
                  flush=True)
    os.chdir(cwd)
    json.dump(out, open(SIG_FIX, "w"))
    return out


def run_trade(df, s, k_ch, hold, slip):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(c)
    i, rr = s["i"], s["rr"]
    long = s["dir"] == "long"
    e = s["e"] * (1 + slip) if long else s["e"] * (1 - slip)
    risk = s["risk"]
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak, end, j = e, min(n - 1, i + hold), i
    out = None
    while j <= end:
        gain = (h[j] - e) / e if long else (e - l[j]) / e
        if (long and l[j] <= sl) or (not long and h[j] >= sl):
            out = (sl - e) / e if long else (e - sl) / e
            break
        if gain >= tp_pct:
            out = tp_pct
            break
        peak = max(peak, h[j]) if long else min(peak, l[j])
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k_ch * a) if long else (peak + k_ch * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if out is None:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), out - FEE - slip


def sim(frames, sigs, gates, lo, hi, k, hold, use_gate, slip=SLIP):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        if use_gate and (gates[sym][i - 1] > 0) != (s["dir"] == "long"):
            continue
        ei, p = run_trade(frames[sym], s, k, hold, slip)
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def cell(p):
    if len(p) < 10:
        return f"{len(p)}건 표본부족"
    a = np.array(p) * 100
    w = (a > 0).sum()
    return (f"{len(a):>4}건 승{100*w/len(a):>2.0f}% {a.sum():+7.1f}% "
            f"(건당 {a.mean():+.3f}±{a.std(ddof=1)/np.sqrt(len(a)):.3f})")


def main():
    frames = load("15m")
    n0 = len(next(iter(frames.values())))
    mid = n0 // 2
    print(f"  8403 15분봉 · {len(frames)}종목 · 180일 · 미끄러짐 {SLIP*100:.2f}%(진입·청산 각)")
    sigs = get_signals(frames)
    print(f"  신호 {sum(len(v) for v in sigs.values())}건 (결함 버전은 3925건)")
    ema = lambda x, s: pd.Series(x).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, GATE), 1, -1)
             for s, d in frames.items()}

    print("\n  " + "═" * 84)
    print(f"  {'설정':<26}{'봉인 앞90일':>29}{'개발 뒤90일':>29}")
    print("  " + "─" * 84)
    rows = [("게이트 없음 · K=4.0", 4.0, 24, False),
            ("게이트 ON · K=2.0", 2.0, 24, True),
            ("게이트 ON · K=3.0", 3.0, 24, True),
            ("게이트 ON · K=4.0 (현행)", 4.0, 24, True),
            ("게이트 ON · K=6.0", 6.0, 24, True),
            ("게이트 ON · K=4.0 · 48봉", 4.0, 48, True),
            ("게이트 ON · K=4.0 · 96봉", 4.0, 96, True)]
    for nm, k, hd, gt in rows:
        a = sim(frames, sigs, gates, 0, mid, k, hd, gt)
        b = sim(frames, sigs, gates, mid, n0, k, hd, gt)
        print(f"  {nm:<26}{cell(a):>29}{cell(b):>29}")
    print("  " + "─" * 84)
    print("  참고: 결함 버전에서는 게이트없음 −107%/−151%, 게이트ON K4.0 +30.1%/+43.4%였다.")
    print("  실거래 실측: 건당 −0.147%")


if __name__ == "__main__":
    main()
