"""
8407 기저 신호 교체 탐색 — 사전 확정 기준으로만 판정한다.

────────────────────────────────────────────────────────────────
채택 기준 (결과를 보기 전에 확정. 사후 조정 금지)
────────────────────────────────────────────────────────────────
  ① 기간 3분할 전부 순손익 > 0
       한 국면에서만 벌면 국면 운이지 엣지가 아니다.
  ② 전 구간 흑자 종목 ≥ 3/4
       한 종목이 캐리하면 종목 특이현상이다.
  ③ 이웃 파라미터도 ①②를 통과
       고립된 한 점만 좋으면 과최적화다.
  ④ 총 진입 ≥ 100건
       표본이 작으면 무엇도 판정할 수 없다.

  넷을 모두 통과한 것만 라이브에 넣는다. 하나라도 못 넘기면 넣지 않는다.
────────────────────────────────────────────────────────────────
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest_8407 import SYMBOLS, load, simulate, Variant, FEE_MAKER, FEE_TAKER
from signals import candidates

MIN_TRADES = 100
N_SPLIT = 3
MIN_POS_SYMBOLS = 3

# 보유 기간은 신호 지평에 맞춰야 한다.
# 4일치 추세를 보면서 6시간 만에 강제 청산하면 신호가 실현될 시간이 없다.
# 15분봉 기준 24=6시간, 96=1일, 384=4일, 960=10일.
HOLD_BARS = (24, 96, 384, 960)


def make_cfg(hold):
    """비용 구조: 진입 maker + TP 지정가(maker) + SL 스톱마켓(taker).

    SL만 테이커인 이유는 안전이다. 손절을 지정가로 걸면 급락 시 체결되지 않는다.
    """
    return Variant("sweep", timeout_bars=0, entry_fee=FEE_MAKER,
                   exit_fee=FEE_TAKER, tp_exit_fee=FEE_MAKER, max_hold_bars=hold)


def evaluate(sig, data, cfg):
    """한 신호를 전 구간·분할·종목별로 평가."""
    full_by_symbol, all_trades = {}, []
    for s, df in data.items():
        t = simulate(df, sig, cfg)
        full_by_symbol[s] = sum(x["net"] for x in t)
        all_trades += t

    parts = []
    for k in range(N_SPLIT):
        tot, n = 0.0, 0
        for s, df in data.items():
            lo = len(df) * k // N_SPLIT
            hi = len(df) * (k + 1) // N_SPLIT
            t = simulate(df.iloc[lo:hi].reset_index(drop=True), sig, cfg)
            tot += sum(x["net"] for x in t)
            n += len(t)
        parts.append((tot, n))

    return {
        "name": f"{sig.name}/H{cfg.max_hold_bars}",
        "sig": sig.name,
        "hold": cfg.max_hold_bars,
        "trades": len(all_trades),
        "net": sum(x["net"] for x in all_trades),
        "by_symbol": full_by_symbol,
        "pos_symbols": sum(1 for v in full_by_symbol.values() if v > 0),
        "parts": parts,
        "parts_all_pos": all(p[0] > 0 for p in parts),
    }


def passes_core(r):
    """①②④ — 이웃 조건(③)은 전체를 본 뒤 별도 판정."""
    return (r["parts_all_pos"]
            and r["pos_symbols"] >= MIN_POS_SYMBOLS
            and r["trades"] >= MIN_TRADES)


def family(r):
    """계열 + 보유기간. 같은 계열 안에서 이웃 파라미터가 함께 통과하는지 본다."""
    return (r["sig"].split("-")[0], r["hold"])


def main():
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = load(s)
        except FileNotFoundError:
            pass
    if not data:
        print("데이터 없음")
        return

    k0 = next(iter(data))
    print(f"기간 {data[k0].timestamp.iloc[0]} ~ {data[k0].timestamp.iloc[-1]}  "
          f"({len(data[k0])}봉 × {len(data)}종목)\n")

    results = []
    for hold in HOLD_BARS:
        cfg = make_cfg(hold)
        for sig in candidates():
            r = evaluate(sig, data, cfg)
            results.append(r)
            mark = "◎" if passes_core(r) else "·"
            parts = " ".join(f"{p[0]:+6.2f}" for p in r["parts"])
            print(f"{mark} {r['name']:22s} {r['trades']:5d}건 순 {r['net']:+7.2f} | "
                  f"3분할 {parts} | 흑자 {r['pos_symbols']}/4")

    core = [r for r in results if passes_core(r)]
    print(f"\n①②④ 통과: {len(core)}건 / 전체 {len(results)}")
    if not core:
        print("→ 채택 없음. 기저 신호 교체를 진행하지 않는다.")
        return

    # ③ 이웃 파라미터 검사 — 같은 (계열, 보유기간)에서 2건 이상 통과해야 고립점이 아니다
    from collections import Counter
    fam = Counter(family(r) for r in core)
    final = [r for r in core if fam[family(r)] >= 2]

    print("계열별 통과 수:", {f"{k[0]}/H{k[1]}": v for k, v in fam.items()})
    print(f"③까지 통과: {len(final)}건")
    for r in sorted(final, key=lambda x: -x["net"]):
        syms = " ".join(f"{s.split('/')[0][:4]}:{v:+5.2f}" for s, v in r["by_symbol"].items())
        print(f"   ★ {r['name']:22s} 순 {r['net']:+7.2f}  "
              f"3분할 {' '.join(f'{p[0]:+.2f}' for p in r['parts'])} | {syms}")
    if not final:
        print("→ 통과한 것이 고립점뿐. 과최적화로 보고 채택하지 않는다.")


if __name__ == "__main__":
    main()
