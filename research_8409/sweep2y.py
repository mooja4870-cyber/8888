"""
2년치(2024-08-01 ~ 2026-08-27) · 10종목으로 전략을 재탐색한다.

배경 — 7개월 표본의 한계를 실증했다.
  8407에 배포한 1h MOM-12/H24는 2026-02~08 7개월에서 4/4 종목 흑자였으나,
  2년으로 늘리면 비관 가정 -8.38, 흑자종목 1/4로 뒤집힌다.
  세 번째 6개월 구간에서 -17.54를 냈다. 표본 창이 짧으면 국면 운을 엣지로 오인한다.

────────────────────────────────────────────────────────────────
채택 기준 (결과를 보기 전에 확정. 사후 조정 금지)
────────────────────────────────────────────────────────────────
  ① 4분할(각 6개월) 전부 순손익 > 0
  ② 흑자 종목 비율 >= 70%
  ③ 이웃 파라미터도 ①②를 통과 (고립점 배제)
  ④ 총 진입 >= 200건
  ⑤ 비관 비용(전부 taker)에서 판정 — 메이커 체결을 가정하지 않는다
────────────────────────────────────────────────────────────────
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["BT_DATA_DIR"] = os.path.join(HERE, "data")
sys.path.insert(0, "/Users/l/project/8888/research_8407")

import backtest_8407 as B
B.DATA_DIR = os.environ["BT_DATA_DIR"]
from backtest_8407 import load, simulate, Variant, FEE_TAKER, FEE_MAKER
from signals import Momentum, MomentumVolFilter, EmaCross, Donchian
from sweep_tf import resample

UNIVERSE = ["SOL/USDT:USDT", "ETH/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT",
            "BNB/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT",
            "LINK/USDT:USDT", "LTC/USDT:USDT", "BTC/USDT:USDT"]

N_SPLIT = 4
MIN_TRADES = 200
MIN_POS_RATIO = 0.70

# 봉 길이별 보유 상한 — 실시간 기준으로 대략 같은 기간이 되도록 맞춘다
TF_GRID = {
    "1h": ("1h", (12, 24, 48, 96)),          # 0.5일 / 1일 / 2일 / 4일
    "4h": ("4h", (6, 12, 24, 42)),           # 1일 / 2일 / 4일 / 7일
    "1d": ("1D", (3, 7, 14, 30)),
}


def families(tf):
    """봉 길이에 맞춰 지평을 실시간 기준으로 비슷하게 잡는다."""
    if tf == "1h":
        moms = (4, 8, 12, 16, 24, 36, 48, 72)
        emas = ((9, 21), (12, 48), (24, 96))
        dons = (12, 24, 48, 96)
    elif tf == "4h":
        moms = (3, 6, 9, 12, 18, 24, 36)
        emas = ((9, 21), (12, 48), (6, 24))
        dons = (6, 12, 24, 48)
    else:
        moms = (3, 5, 8, 12, 20, 30)
        emas = ((5, 20), (10, 30), (8, 21))
        dons = (5, 10, 20, 40)
    out = [Momentum(n) for n in moms]
    out += [MomentumVolFilter(n) for n in moms[:4]]
    out += [EmaCross(f, s) for f, s in emas]
    out += [Donchian(n) for n in dons]
    return out


def evaluate(sig, data, cfg):
    t, bysym = [], {}
    for s, df in data.items():
        u = simulate(df, sig, cfg)
        bysym[s] = sum(x["net"] for x in u)
        t += u
    if not t:
        return None
    parts = []
    for k in range(N_SPLIT):
        tot = 0.0
        for s, df in data.items():
            lo, hi = len(df) * k // N_SPLIT, len(df) * (k + 1) // N_SPLIT
            tot += sum(x["net"] for x in simulate(df.iloc[lo:hi].reset_index(drop=True), sig, cfg))
        parts.append(tot)
    pos = sum(1 for v in bysym.values() if v > 0)
    g = sum(x["gross"] for x in t)
    return {
        "sig": sig.name, "hold": cfg.max_hold_bars,
        "n": len(t), "gross": g, "net": sum(x["net"] for x in t),
        "parts": parts, "pos": pos, "nsym": len(bysym), "bysym": bysym,
        "edge_bp": 10000 * g / (len(t) * 7.0),
        "ok": (all(p > 0 for p in parts)
               and pos / len(bysym) >= MIN_POS_RATIO
               and len(t) >= MIN_TRADES),
    }


def main():
    raw = {s: load(s) for s in UNIVERSE}
    results = []

    for tf, (rule, holds) in TF_GRID.items():
        data = {s: (raw[s] if tf == "15m" else resample(raw[s], rule)) for s in raw}
        n = len(next(iter(data.values())))
        print(f"\n━━ {tf}  ({n}봉 × {len(data)}종목) ━━")
        for hold in holds:
            # ⑤ 비관 비용으로 판정한다
            cfg = Variant("x", timeout_bars=0, entry_fee=FEE_TAKER,
                          exit_fee=FEE_TAKER, max_hold_bars=hold)
            for sig in families(tf):
                r = evaluate(sig, data, cfg)
                if r is None:
                    continue
                r["tf"] = tf
                results.append(r)
                if r["ok"]:
                    print(f"  ◎ {r['sig']:12s} H{hold:<4d} {r['n']:5d}건 "
                          f"순 {r['net']:+8.2f} 건당 {r['edge_bp']:+6.1f}bp "
                          f"| 4분할 {' '.join(f'{p:+6.2f}' for p in r['parts'])} "
                          f"| 흑자 {r['pos']}/{r['nsym']}")

    print("\n━━ 타임프레임별 요약 ━━")
    for tf in TF_GRID:
        sub = [r for r in results if r["tf"] == tf]
        if not sub:
            continue
        best = max(sub, key=lambda r: r["net"])
        print(f"  {tf:3s} 후보 {len(sub):3d}  평균 건당총이익 "
              f"{sum(r['edge_bp'] for r in sub)/len(sub):+6.2f}bp  "
              f"최고 {best['net']:+8.2f} ({best['sig']}/H{best['hold']})  "
              f"통과 {sum(1 for r in sub if r['ok'])}건")

    ok = [r for r in results if r["ok"]]
    print(f"\n①②④⑤ 통과: {len(ok)}건 / 전체 {len(results)}")
    if not ok:
        print("→ 2년 기준을 넘는 구성이 없다.")
        return

    from collections import Counter
    fam = Counter((r["tf"], r["sig"].split("-")[0], r["hold"]) for r in ok)
    # ③ 같은 (TF, 계열, 보유)에서 2건 이상이거나, 같은 (TF,계열)에서 보유가 2개 이상 통과
    fam2 = Counter((r["tf"], r["sig"].split("-")[0]) for r in ok)
    final = [r for r in ok if fam[(r["tf"], r["sig"].split("-")[0], r["hold"])] >= 2
             or fam2[(r["tf"], r["sig"].split("-")[0])] >= 3]
    print("계열별 통과:", {f"{k[0]}/{k[1]}": v for k, v in fam2.items()})
    print(f"③까지 통과: {len(final)}건")
    for r in sorted(final, key=lambda x: -x["net"]):
        syms = " ".join(f"{s.split('/')[0][:4]}:{v:+.1f}" for s, v in r["bysym"].items())
        print(f"   ★ {r['tf']:3s} {r['sig']:12s} H{r['hold']:<4d} 순 {r['net']:+8.2f} "
              f"건당 {r['edge_bp']:+6.1f}bp 흑자 {r['pos']}/{r['nsym']}")
        print(f"      4분할 {' '.join(f'{p:+6.2f}' for p in r['parts'])}")
        print(f"      {syms}")
    if not final:
        print("→ 통과한 것이 고립점뿐. 과최적화로 보고 채택하지 않는다.")


if __name__ == "__main__":
    main()
