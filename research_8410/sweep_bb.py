"""
8410 재탐색 — 2년 · 포지션 상한 반영 · 비관 비용.

────────────────────────────────────────────────────────────────
채택 기준 (결과를 보기 전에 확정. 사후 조정 금지)
────────────────────────────────────────────────────────────────
  ① 4분할(각 6개월) 전부 순손익 > 0
  ② 흑자 종목 ≥ 70%
  ③ 이웃 파라미터도 ①②를 통과 (고립점 배제)
  ④ 총 진입 ≥ 100건 (4종목 포트폴리오 기준)
  ⑤ 비관 비용(전부 taker)에서 판정 — 메이커 체결을 가정하지 않는다
  ⑥ 8407(DON-30/H7)·8409(DON-20/H30)와 청산 겹침이 낮을 것 — 함대 분산
────────────────────────────────────────────────────────────────
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["BT_DATA_DIR"] = "/Users/l/project/8888/research_8409/data"
sys.path.insert(0, "/Users/l/project/8888/research_8407")
sys.path.insert(0, "/Users/l/project/8888/research_8409")
sys.path.insert(0, HERE)

import backtest_8407 as B
B.DATA_DIR = os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from sweep_tf import resample
from portfolio import simulate_portfolio
from bb_signal import BollingerBreakout, KeltnerBreakout

FOUR = ["SOL/USDT:USDT", "ETH/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT"]
SEED = 10.0
MIN_TRADES = 100
MIN_POS_RATIO = 0.70

# 1h는 비용에 불리한 것이 이미 확인돼(8407·8409에서 통과 0건) 뒤로 돌린다.
# 환경변수 BT_TF로 개별 실행 가능.
_ALL = {
    "4h": ("4h", (6, 12, 24, 42)),
    "1d": ("1D", (3, 7, 14, 30)),
    "1h": ("1h", (12, 24, 48, 96)),
}
_only = os.environ.get("BT_TF")
TF_GRID = {_only: _ALL[_only]} if _only in _ALL else {k: _ALL[k] for k in ("4h", "1d")}


def stat(data, sig, hold, cap=4, notional=7.0):
    tr = sorted(simulate_portfolio(data, sig, hold, max_positions=cap, notional=notional),
                key=lambda x: x["t"])
    if not tr:
        return None
    bal = mn = peak = SEED
    dd = 0.0
    for x in tr:
        bal += x["net"]
        mn = min(mn, bal)
        peak = max(peak, bal)
        dd = max(dd, peak - bal)
    ts = [x["t"] for x in tr]
    parts = [sum(x["net"] for x in tr
                 if ts[len(ts) * k // 4] <= x["t"] <= ts[min(len(ts) - 1, len(ts) * (k + 1) // 4)])
             for k in range(4)]
    bysym = {}
    for x in tr:
        bysym[x["symbol"]] = bysym.get(x["symbol"], 0.0) + x["net"]
    g = sum(x["gross"] for x in tr)
    pos = sum(1 for v in bysym.values() if v > 0)
    return {"n": len(tr), "gross": g, "net": sum(x["net"] for x in tr),
            "bal": bal, "mn": mn, "dd": 100 * dd / peak, "parts": parts,
            "pos": pos, "nsym": len(bysym), "bysym": bysym, "trades": tr,
            "edge": 10000 * g / (len(tr) * notional),
            "ok": (all(p > 0 for p in parts)
                   and pos / len(bysym) >= MIN_POS_RATIO
                   and len(tr) >= MIN_TRADES)}


def main():
    raw = {s: load(s) for s in FOUR}
    results = []
    for tf, (rule, holds) in TF_GRID.items():
        data = {s: resample(raw[s], rule) for s in FOUR}
        print(f"\n━━ {tf} ({len(next(iter(data.values())))}봉 × 4종목) ━━")
        cands = ([BollingerBreakout(p, k) for p in (10, 20, 30, 50) for k in (1.5, 2.0, 2.5)]
                 + [KeltnerBreakout(p, k) for p in (10, 20, 30, 50) for k in (1.5, 2.0, 2.5)])
        for hold in holds:
            for sig in cands:
                r = stat(data, sig, hold)
                if r is None:
                    continue
                r["tf"], r["sig"], r["hold"] = tf, sig.name, hold
                results.append(r)
                if r["ok"]:
                    print(f"  ◎ {sig.name:12s} H{hold:<4d} {r['n']:5d}건 "
                          f"순 {r['net']:+8.2f} 건당 {r['edge']:+6.1f}bp 낙폭 {r['dd']:3.0f}% "
                          f"| 4분할 {' '.join(f'{p:+6.2f}' for p in r['parts'])} "
                          f"| 흑자 {r['pos']}/4")

    ok = [r for r in results if r["ok"]]
    print(f"\n①②④⑤ 통과: {len(ok)}건 / 전체 {len(results)}")
    for tf in TF_GRID:
        sub = [r for r in results if r["tf"] == tf]
        if sub:
            best = max(sub, key=lambda r: r["net"])
            print(f"  {tf:3s} 후보 {len(sub):3d}  최고 {best['net']:+8.2f} "
                  f"({best['sig']}/H{best['hold']})  통과 {sum(1 for r in sub if r['ok'])}건")
    if not ok:
        print("→ 2년 기준을 넘는 구성이 없다.")
        return

    from collections import Counter
    fam = Counter((r["tf"], r["sig"].split("-")[0]) for r in ok)
    final = [r for r in ok if fam[(r["tf"], r["sig"].split("-")[0])] >= 2]
    print("계열별 통과:", {f"{k[0]}/{k[1]}": v for k, v in fam.items()})
    print(f"③까지 통과: {len(final)}건")
    for r in sorted(final, key=lambda x: -x["net"])[:8]:
        syms = "  ".join(f"{s.split('/')[0]}:{v:+.2f}" for s, v in sorted(r["bysym"].items()))
        print(f"   ★ {r['tf']:3s} {r['sig']:12s} H{r['hold']:<4d} {r['n']:4d}건 "
              f"순 {r['net']:+8.2f} 최저${r['mn']:.2f} 낙폭{r['dd']:.0f}%")
        print(f"      4분할 {' '.join(f'{p:+6.2f}' for p in r['parts'])} | {syms}")


if __name__ == "__main__":
    main()
