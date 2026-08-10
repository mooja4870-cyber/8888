#!/usr/bin/env python3
"""verify_gate_design.py — 방향 게이트 설계안 비교

(다) 안: 바스켓 게이트와 종목별 추세필터를 같은 조건에서 재보고 나은 쪽을 채택한다.
어느 쪽이든 국면이 정반대인 두 구간(봉인=하락, 개발=상승)에서 **모두** 개선되어야
구조적 개선으로 인정한다. 한쪽만 좋으면 국면 의존이므로 기각한다.

  가 바스켓 게이트   — 15종목 정규화 평균 지수가 장기 EMA 위면 롱만, 아래면 숏만.
                       시장 전체 방향을 본다. 종목 간 상태 공유가 필요하다.
  나 종목별 추세필터 — 각 종목이 자기 장기 EMA 위면 롱만, 아래면 숏만.
                       신호 시점 df에 이미 있는 값이라 구현이 단순하다.

본전보호는 이미 검증돼 전 조합에서 OFF로 고정한다.
신호 수집이 느려(종목당 ~50초) 결과를 디스크에 캐시하고, 이후 실험은 캐시를 재사용한다.
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = "/Users/l/project/8403"
CACHE = "/Users/l/project/8888/lab_cache_180"
SIGCACHE = "/Users/l/project/8888/lab/_sigcache_8403_180d.json"
WARMUP = 800
sys.path.insert(0, BOT); os.chdir(BOT)
sys.path.insert(0, "/Users/l/project/8888")
from strategy_validator import simulate_real


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


def get_signals(frames):
    """신호는 게이트와 무관하므로 한 번만 뽑아 캐시한다."""
    if os.path.exists(SIGCACHE):
        d = json.load(open(SIGCACHE))
        if set(d) == set(frames) and d.get("_n") != 0:
            print("  신호 캐시 재사용", flush=True)
            return {k: v for k, v in d.items() if not k.startswith("_")}
    from core.strategy import StrategyEngine
    strat = StrategyEngine()
    out = {}
    for s, df in frames.items():
        sg = []
        for i in range(WARMUP, len(df) - 1):
            g = strat.generate_signal(df.iloc[i-WARMUP:i], s)
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


def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    sigs = get_signals(frames)
    cfg = dict(json.load(open(f"{BOT}/config.json")))
    cfg["USE_BE_GUARD"] = False                      # 검증 완료분은 고정

    idx = np.mean([d["close"].values/d["close"].values[0] for d in frames.values()], axis=0)
    def ema(a, span): return pd.Series(a).ewm(span=span, adjust=False).mean().values
    basket = {span: np.where(idx > ema(idx, span), 1, -1) for span in (192, 384, 768)}
    trend = {span: {s: np.where(d["close"].values > ema(d["close"].values, span), 1, -1)
                    for s, d in frames.items()} for span in (192, 384, 768)}

    def gate_none(s, i):    return True
    def gate_basket(span):
        return lambda s, i, d: (basket[span][i] > 0) == (d == "long")
    def gate_trend(span):
        return lambda s, i, d: (trend[span][s][i] > 0) == (d == "long")
    def gate_both(span):
        return lambda s, i, d: ((basket[span][i] > 0) == (d == "long")
                                and (trend[span][s][i] > 0) == (d == "long"))

    variants = [("게이트 없음 (본전보호 OFF만)", None)]
    for span, lab in ((192, "EMA192=2일"), (384, "EMA384=4일"), (768, "EMA768=8일")):
        variants.append((f"가 바스켓 {lab}", gate_basket(span)))
        variants.append((f"나 종목별 {lab}", gate_trend(span)))
    variants.append(("다 바스켓+종목별 EMA384", gate_both(384)))

    windows = [("봉인 앞90일(하락)", 0, mid), ("개발 뒤90일(상승)", mid, n0)]
    print("  " + "═"*82)
    print(f"  {'설계안':<30}" + "".join(f"{w[0]:>26}" for w in windows))
    print("  " + "─"*82)
    base = {}
    for nm, gfn in variants:
        cells, nets = [], []
        for wn, lo, hi in windows:
            tot, wins, pnl = 0, 0, 0.0
            for s, df in frames.items():
                sg = [x for x in sigs[s] if lo <= x["i"] < hi]
                if gfn:
                    sg = [x for x in sg if gfn(s, x["i"], x["dir"])]
                if not sg:
                    continue
                r = simulate_real(sg, df, cfg)
                tot += r["n"]; wins += r["win"]; pnl += r["net"]
            wr = 100*wins/tot if tot else 0
            nets.append(pnl*100)
            cells.append(f"{tot}건 {wr:.0f}% {pnl*100:+.1f}%")
        if not base:
            base = {"n": nets}
        ok = all(nets[k] > base["n"][k] for k in range(2)) and gfn is not None
        print(f"  {nm:<30}" + "".join(f"{x:>26}" for x in cells) + ("  ✅" if ok else ""))
    print("  " + "─"*82)
    print("  ✅ = 두 구간 모두 '게이트 없음'보다 개선. 채택 후보.")


if __name__ == "__main__":
    main()
