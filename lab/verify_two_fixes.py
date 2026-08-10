#!/usr/bin/env python3
"""verify_two_fixes.py — 실거래 반영 예정 2개 변경의 사전 검증

오늘 8개 전략 후보가 전부 봉인 구간에서 무너졌다. 그래서 실거래 8봇에 손대기 전에,
반영하려는 변경 자체를 **개발·봉인 양쪽에서 따로** 확인한다.
국면이 정반대인 두 구간(개발=바스켓 +222%, 봉인=바스켓 −30%)에서 모두 개선되어야
국면 의존이 아닌 구조적 개선이라고 말할 수 있다.

  변경① 본전보호 OFF  — 손절선을 본전으로 끌어올리면 승률은 오르지만 승리 폭이 잘린다.
  변경② 방향 게이트   — 시장이 오를 때 롱만, 내릴 때 숏만. 상승장 숏 자해를 막는다.

진입 신호는 실거래 전략(MFI 다이버전스, 8403)을 그대로 쓰고 청산만 바꿔 비교한다.
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = "/Users/l/project/8403"
CACHE = "/Users/l/project/8888/lab_cache_180"
FEE = 0.001
sys.path.insert(0, BOT); os.chdir(BOT)
sys.path.insert(0, "/Users/l/project/8888")
from strategy_validator import simulate_real

WARMUP = 800   # 지표 수렴에 충분한 창(200EMA + 다이버전스 40봉). 전체 이력 대신
               # 고정 창을 넘겨 O(n^2) → O(n)으로 낮춘다. 결과 차이는 무시할 수준.


def collect_signals_fast(strategy, df, sym):
    """봉마다 최근 WARMUP봉만 넘겨 신호를 수집한다(원본 collect_signals와 동일 규약)."""
    n = len(df)
    sigs = []
    for i in range(WARMUP, n - 1):
        s = strategy.generate_signal(df.iloc[i - WARMUP:i], sym)
        if s.direction == "none":
            continue
        e, sl, tp = s.close, s.swing_sl_price, s.tp1_price
        if not (e > 0 and sl > 0 and tp > 0):
            continue
        risk = abs(e - sl) / e
        if risk <= 0:
            continue
        sigs.append({"i": i, "dir": s.direction, "e": e, "risk": risk,
                     "rr": abs(tp - e) / e / risk})
    return sigs

def load():
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/binance_15m_*.json")):
        df = pd.DataFrame(json.load(open(p)), columns=["ts","open","high","low","close","volume"])
        c,h,l = df["close"],df["high"],df["low"]; pc=c.shift(1)
        tr = pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=14,adjust=False).mean()
        out[os.path.basename(p).split("15m_")[1].split("_USDT")[0]] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k,v in out.items()}

def build_gate(frames):
    """바스켓 지수(15종목 정규화 평균)가 장기 EMA 위면 롱만, 아래면 숏만."""
    idx = np.mean([d["close"].values/d["close"].values[0] for d in frames.values()], axis=0)
    ema = pd.Series(idx).ewm(span=384, adjust=False).mean().values
    return np.where(idx > ema, 1, -1)

def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0//2
    gate = build_gate(frames)
    from core.strategy import StrategyEngine
    cfg_live = json.load(open(f"{BOT}/config.json"))
    strat = StrategyEngine()          # 봇의 살아있는 CFG(config.json)를 그대로 사용
    print(f"  {len(frames)}종목 · {n0}봉 = {n0*15/60/24:.0f}일 · 전략=MFI 다이버전스(8403 실거래)", flush=True)

    sigs = {}
    for s, df in frames.items():
        sigs[s] = collect_signals_fast(strat, df, s)
        print(f"    {s:<8} 신호 {len(sigs[s])}건", flush=True)

    combos = [("현행 (본전보호 ON · 게이트 없음)", True,  False),
              ("본전보호 OFF만",                  False, False),
              ("게이트만",                        True,  True),
              ("본전보호 OFF + 게이트 ★",         False, True)]
    windows = [("봉인 앞90일(하락국면)", 0, mid), ("개발 뒤90일(상승국면)", mid, n0)]

    print("  " + "═"*86)
    print(f"  {'설정':<32}" + "".join(f"{w[0]:>26}" for w in windows))
    print("  " + "─"*86)
    for nm, be, use_gate in combos:
        cells = []
        for _, lo, hi in windows:
            tot, wins, pnl = 0, 0, 0.0
            for s, df in frames.items():
                sg = [x for x in sigs[s] if lo <= x["i"] < hi]
                if use_gate:
                    sg = [x for x in sg if (gate[x["i"]] > 0) == (x["dir"] == "long")]
                if not sg: continue
                c = dict(cfg_live); c["USE_BE_GUARD"] = be
                r = simulate_real(sg, df, c)
                tot += r["n"]; wins += r["win"]; pnl += r["net"]
            wr = 100*wins/tot if tot else 0
            cells.append(f"{tot}건 {wr:.0f}% {pnl*100:+.1f}%")
        print(f"  {nm:<32}" + "".join(f"{x:>26}" for x in cells))
    print("  " + "─"*86)
    print("  판정: 두 구간 모두 현행보다 개선되어야 구조적 개선. 한쪽만이면 국면 의존.")

if __name__ == "__main__":
    main()
