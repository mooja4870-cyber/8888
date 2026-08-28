"""
타임프레임 스윕 — 15분봉이 비용에 불리한지 확인한다.

15분봉에서 측정된 사실:
    건당 총이익 ≈ +0.06%,  왕복 비용 0.04~0.07%
    → 엣지가 비용과 같은 크기라 순손익이 0 근처에 붙는다.

봉을 늘리면 한 건이 잡는 움직임이 커지므로 고정비 비중이 떨어진다.
같은 신호·같은 기준으로 15m / 1h / 4h / 1d 를 비교한다.

판정 기준은 sweep.py와 동일하며 사전 확정된 것을 그대로 쓴다.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from backtest_8407 import SYMBOLS, load, simulate, Variant, FEE_MAKER, FEE_TAKER
from signals import Momentum, MomentumVolFilter, EmaCross, Donchian

MIN_TRADES = 100
N_SPLIT = 3
MIN_POS_SYMBOLS = 3

# 봉 길이별 보유 상한 — 실시간으로 대략 같은 기간이 되도록 맞춘다
TFS = {
    "15m": ("15min", [24, 96, 384]),      # 6시간 / 1일 / 4일
    "1h":  ("1h",    [6, 24, 96]),
    "4h":  ("4h",    [6, 12, 42]),        # 1일 / 2일 / 1주
    "1d":  ("1D",    [3, 7, 30]),
}


def resample(df, rule):
    d = df.set_index("timestamp")
    out = d.resample(rule).agg({"open": "first", "high": "max",
                                "low": "min", "close": "last", "volume": "sum"})
    return out.dropna().reset_index()


def cands():
    return ([Momentum(n) for n in (4, 12, 24, 48)]
            + [MomentumVolFilter(n) for n in (12, 24, 48)]
            + [EmaCross(f, s) for f, s in ((9, 21), (12, 48), (24, 96))]
            + [Donchian(n) for n in (12, 24, 48)])


def main():
    raw = {s: load(s) for s in SYMBOLS}
    rows = []

    for tf, (rule, holds) in TFS.items():
        data = {s: (raw[s] if tf == "15m" else resample(raw[s], rule)) for s in raw}
        n = len(next(iter(data.values())))
        print(f"\n━━ {tf}  ({n}봉 × {len(data)}종목) ━━")

        for hold in holds:
            cfg = Variant("x", timeout_bars=0, entry_fee=FEE_MAKER,
                          exit_fee=FEE_TAKER, tp_exit_fee=FEE_MAKER,
                          max_hold_bars=hold)
            for sig in cands():
                t, bysym = [], {}
                for s, df in data.items():
                    u = simulate(df, sig, cfg)
                    bysym[s] = sum(x["net"] for x in u)
                    t += u
                if len(t) < MIN_TRADES:
                    continue

                parts = []
                for k in range(N_SPLIT):
                    tot = 0.0
                    for s, df in data.items():
                        lo, hi = len(df) * k // N_SPLIT, len(df) * (k + 1) // N_SPLIT
                        tot += sum(x["net"] for x in
                                   simulate(df.iloc[lo:hi].reset_index(drop=True), sig, cfg))
                    parts.append(tot)

                g = sum(x["gross"] for x in t)
                f = sum(x["fee"] for x in t)
                pos = sum(1 for v in bysym.values() if v > 0)
                ok = all(p > 0 for p in parts) and pos >= MIN_POS_SYMBOLS
                rows.append({"tf": tf, "hold": hold, "sig": sig.name, "n": len(t),
                             "gross": g, "net": g - f, "parts": parts,
                             "pos": pos, "ok": ok,
                             "edge_bp": 10000 * g / (len(t) * 7.0)})
                if ok:
                    print(f"  ◎ {sig.name:12s} H{hold:<4d} {len(t):5d}건 "
                          f"순 {g-f:+7.2f} 총 {g:+7.2f} 건당 {10000*g/(len(t)*7.0):+5.1f}bp "
                          f"| 3분할 {' '.join(f'{p:+.2f}' for p in parts)} | 흑자 {pos}/4")

    print("\n━━ 타임프레임별 요약 (건당 총이익 = 비용을 넘어야 하는 값) ━━")
    print("  왕복 비용: 진입maker 2bp + 청산 TP 2bp / SL 5bp  →  대략 4~7bp")
    for tf in TFS:
        sub = [r for r in rows if r["tf"] == tf]
        if not sub:
            continue
        best = max(sub, key=lambda r: r["net"])
        avg_edge = sum(r["edge_bp"] for r in sub) / len(sub)
        npass = sum(1 for r in sub if r["ok"])
        print(f"  {tf:4s} 후보 {len(sub):3d}  평균 건당총이익 {avg_edge:+6.2f}bp  "
              f"최고순손익 {best['net']:+7.2f} ({best['sig']}/H{best['hold']})  통과 {npass}건")

    passed = [r for r in rows if r["ok"]]
    print(f"\n①②④ 통과: {len(passed)}건 / 전체 {len(rows)}")
    if not passed:
        print("→ 어떤 타임프레임에서도 채택 기준을 넘지 못했다.")
        return

    from collections import Counter
    fam = Counter((r["tf"], r["sig"].split("-")[0]) for r in passed)
    final = [r for r in passed if fam[(r["tf"], r["sig"].split("-")[0])] >= 2]
    print("계열별 통과:", {f"{k[0]}/{k[1]}": v for k, v in fam.items()})
    print(f"③까지 통과: {len(final)}건")
    for r in sorted(final, key=lambda x: -x["net"]):
        print(f"   ★ {r['tf']:4s} {r['sig']:12s} H{r['hold']:<4d} 순 {r['net']:+7.2f} "
              f"건당 {r['edge_bp']:+5.1f}bp 3분할 {' '.join(f'{p:+.2f}' for p in r['parts'])}")
    if not final:
        print("→ 통과한 것이 고립점뿐. 과최적화로 보고 채택하지 않는다.")


if __name__ == "__main__":
    main()
