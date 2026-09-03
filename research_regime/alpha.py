"""알파/베타 분리 — 국면별 '그냥 보유' 수익을 빼고 남는 게 진짜 엣지다.

상승장에서 롱을 잡으면 신호가 없어도 돈을 번다. 그 몫(베타)을 빼지 않으면
어떤 신호든 상승장에서 훌륭해 보인다. 국면별 무조건 롱 수익률을 기준선으로 두고,
전략 수익에서 그만큼을 뺀 초과분(알파)을 잰다.
"""
import numpy as np, pandas as pd
import regime as R
from screen import CANDS, HOLDS, COST_BP


def run():
    base, strat = [], []
    for sym in R.symbols():
        d = R.load(sym); reg = R.classify(d); op = d["open"].values
        # 기준선: 매일 롱을 잡았을 때의 h일 수익 (비용 동일 차감)
        for h in HOLDS:
            for i in range(len(d) - h - 2):
                if reg.iloc[i] is None: continue
                e, x = op[i + 1], op[i + 1 + h]
                if not (e > 0 and x > 0): continue
                base.append((h, reg.iloc[i], (x / e - 1) * 10000 - COST_BP))
        for name, fn in CANDS:
            s = fn(d).values
            for h in HOLDS:
                for i in range(len(d) - h - 2):
                    if s[i] == 0 or reg.iloc[i] is None: continue
                    e, x = op[i + 1], op[i + 1 + h]
                    if not (e > 0 and x > 0): continue
                    r = (x / e - 1) * 10000
                    strat.append((name, h, reg.iloc[i], s[i], r * s[i] - COST_BP, r - COST_BP))
    return (pd.DataFrame(base, columns=["hold", "regime", "bp"]),
            pd.DataFrame(strat, columns=["strategy", "hold", "regime", "dir", "bp", "long_bp"]))


if __name__ == "__main__":
    b, s = run()
    print("국면별 '무조건 롱' 기준선 (건당 bp, 비용 차감 후)\n", flush=True)
    bp = b.pivot_table(index="hold", columns="regime", values="bp", aggfunc="mean")
    for h in HOLDS:
        print("  보유 %2d일   " % h + "  ".join("%s %+8.1f" % (r, bp.loc[h, r])
              for r in ("BULL", "BEAR", "RANGE")))
    print("\n전략 순엣지에서 기준선을 뺀 초과분(알파)\n", flush=True)
    for h in HOLDS:
        print("── 보유 %d일 ──" % h)
        sub = s[s["hold"] == h]
        piv = sub.pivot_table(index="strategy", columns="regime", values="bp", aggfunc="mean")
        for st in piv.index:
            cells = []
            for r in ("BULL", "BEAR", "RANGE"):
                if r not in piv.columns: continue
                cells.append("%s %+8.1f" % (r, piv.loc[st, r] - bp.loc[h, r]))
            print("  %-20s %s" % (st, "  ".join(cells)))
        print()
    print("참고 — 방향별 건수 (롱/숏)", flush=True)
    for st in s["strategy"].unique():
        q = s[(s["strategy"] == st) & (s["hold"] == 20)]
        print("  %-20s 롱 %5d · 숏 %5d" % (st, (q["dir"] == 1).sum(), (q["dir"] == -1).sum()))
