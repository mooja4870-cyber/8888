"""강건성 검증 — 결과를 보기 전에 정한 기준으로만 판정한다.

  ① 이웃 파라미터도 통과해야 한다 (고원이지 뾰족한 점이 아니어야)
  ② 기간을 4분할해 전부 양수여야 한다 (특정 국면 운이 아니어야)
  ③ 종목의 70% 이상에서 양수여야 한다
  ④ 국면별 거래 건수가 최소 100건은 되어야 한다
모두 알파(무조건 롱 기준선을 뺀 초과분) 기준. 비용은 전량 테이커 왕복 10bp.
"""
import numpy as np, pandas as pd
import regime as R
from screen import sig_donchian, COST_BP

HOLD = 20
LENS = [20, 34, 55, 80, 100]


def collect():
    rows = []
    for sym in R.symbols():
        d = R.load(sym); reg = R.classify(d); op = d["open"].values
        dates = d["date"].values
        for n in LENS:
            s = sig_donchian(d, n).values
            for i in range(len(d) - HOLD - 2):
                if reg.iloc[i] is None: continue
                e, x = op[i + 1], op[i + 1 + HOLD]
                if not (e > 0 and x > 0): continue
                base = (x / e - 1) * 10000 - COST_BP          # 무조건 롱
                if s[i] == 0: continue
                net = (x / e - 1) * 10000 * s[i] - COST_BP
                rows.append((sym, n, reg.iloc[i], dates[i + 1], net - base))
    return pd.DataFrame(rows, columns=["sym", "n", "regime", "date", "alpha"])


if __name__ == "__main__":
    df = collect()
    df["q"] = pd.qcut(pd.to_datetime(df["date"]).astype("int64"), 4, labels=["1분기", "2분기", "3분기", "4분기"])
    print("Donchian 알파 — 보유 %d일 · 이웃 파라미터 고원 확인\n" % HOLD, flush=True)
    print("%-6s %-7s %8s %7s %-30s %s" % ("길이", "국면", "평균알파", "건수", "기간 4분할", "흑자종목"), flush=True)
    for n in LENS:
        for r in ("BULL", "BEAR", "RANGE"):
            q = df[(df["n"] == n) & (df["regime"] == r)]
            if q.empty: continue
            parts = q.groupby("q", observed=True)["alpha"].mean()
            bysym = q.groupby("sym")["alpha"].mean()
            pos = (bysym > 0).sum()
            allpos = (parts > 0).all()
            print("%-6d %-7s %+8.0f %7d  %-30s %d/%d %s" % (
                n, r, q["alpha"].mean(), len(q),
                " ".join("%+6.0f" % v for v in parts.values),
                pos, len(bysym),
                "✅" if (allpos and pos / len(bysym) >= 0.7 and len(q) >= 100) else ""))
        print()
