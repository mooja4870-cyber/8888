"""강건성 재검증 — 알파 정의를 바로잡았다.

[이전 오류] 거래 단위로 (전략수익 − 무조건롱수익)을 뺐더니 롱 신호는 항상 0이 됐다.
[올바른 정의] 같은 (종목·국면·기간) 구간 안에서
      알파 = 신호일들의 평균수익 − 그 구간 모든 날의 평균수익
  즉 "그 국면에서 아무 날에나 들어가는 것 대비, 신호가 고른 날이 나은가".

판정 기준 (결과 보기 전 고정)
  ① 기간 4분할 전부 양수  ② 흑자종목 70% 이상  ③ 국면별 거래 100건 이상
  ④ 이웃 파라미터도 함께 통과(고원)
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
        dates = pd.to_datetime(d["date"]).values
        fwd = np.full(len(d), np.nan)
        for i in range(len(d) - HOLD - 2):
            e, x = op[i + 1], op[i + 1 + HOLD]
            if e > 0 and x > 0:
                fwd[i] = (x / e - 1) * 10000 - COST_BP
        sigs = {n: sig_donchian(d, n).values for n in LENS}
        for i in range(len(d) - HOLD - 2):
            if reg.iloc[i] is None or not np.isfinite(fwd[i]):
                continue
            row = {"sym": sym, "regime": reg.iloc[i], "date": dates[i + 1], "fwd": fwd[i]}
            for n in LENS:
                row[f"s{n}"] = sigs[n][i]
            rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = collect()
    df["q"] = pd.qcut(df["date"].astype("int64"), 4, labels=["1분기", "2분기", "3분기", "4분기"])
    print("Donchian 알파 재측정 — 보유 %d일\n" % HOLD, flush=True)
    print("%-5s %-6s %8s %6s  %-30s %-8s %s" % ("길이", "국면", "알파bp", "건수", "기간 4분할(알파)", "흑자종목", "판정"), flush=True)
    for n in LENS:
        col = f"s{n}"
        for r in ("BULL", "BEAR", "RANGE"):
            sub = df[df["regime"] == r]
            if sub.empty: continue
            sig = sub[sub[col] != 0]
            if len(sig) < 20: continue
            # 신호 방향을 반영한 수익 (숏이면 부호 반전) − 그 구간 무조건롱 평균
            def alpha_of(g):
                gs = g[g[col] != 0]
                if gs.empty: return np.nan
                return (gs["fwd"] * gs[col]).mean() - g["fwd"].mean()
            overall = alpha_of(sub)
            parts = sub.groupby("q", observed=True).apply(alpha_of)
            bysym = sub.groupby("sym").apply(alpha_of).dropna()
            pos = (bysym > 0).sum()
            ok = (parts > 0).all() and len(bysym) and pos / len(bysym) >= 0.7 and len(sig) >= 100
            print("%-5d %-6s %+8.0f %6d  %-30s %d/%-6d %s" % (
                n, r, overall, len(sig),
                " ".join("%+6.0f" % v for v in parts.values), pos, len(bysym),
                "✅ 통과" if ok else ""))
        print()
