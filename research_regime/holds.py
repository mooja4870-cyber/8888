"""국면 × 보유기간 격자 — 하락장·횡보장에 맞는 시간대가 따로 있는지 본다."""
import numpy as np, pandas as pd
import regime as R
from screen import sig_donchian, COST_BP
import warnings; warnings.filterwarnings("ignore")

HOLDS = [3, 5, 10, 20, 40]
LENS = [20, 55]


def run():
    rows = []
    for sym in R.symbols():
        d = R.load(sym); reg = R.classify(d); op = d["open"].values
        dates = pd.to_datetime(d["date"]).values
        vol_ok = (d["volume"] > d["volume"].rolling(20).mean()).values
        sigs = {n: sig_donchian(d, n).values for n in LENS}
        for h in HOLDS:
            fwd = np.full(len(d), np.nan)
            for i in range(len(d) - h - 2):
                e, x = op[i + 1], op[i + 1 + h]
                if e > 0 and x > 0:
                    fwd[i] = (x / e - 1) * 10000 - COST_BP
            for i in range(len(d) - h - 2):
                if reg.iloc[i] is None or not np.isfinite(fwd[i]):
                    continue
                r = {"sym": sym, "h": h, "regime": reg.iloc[i], "date": dates[i+1], "fwd": fwd[i]}
                for n in LENS:
                    r[f"D{n}"] = sigs[n][i]
                    r[f"D{n}V"] = sigs[n][i] if vol_ok[i] else 0
                rows.append(r)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = run()
    df["q"] = pd.qcut(df["date"].astype("int64"), 4, labels=list("1234"))
    cols = [f"D{n}" for n in LENS] + [f"D{n}V" for n in LENS]
    print("국면 × 보유기간 알파(bp) · 비관비용 왕복 10bp\n", flush=True)
    for r in ("BEAR", "RANGE"):
        print("── %s ──" % r)
        print("  %-6s %-6s %8s %6s  %-24s %-7s %s" % ("전략","보유","알파","건수","기간4분할","흑자","판정"))
        for k in cols:
            for h in HOLDS:
                sub = df[(df["regime"] == r) & (df["h"] == h)]
                sig = sub[sub[k] != 0]
                if len(sig) < 50: continue
                f = lambda g: ((g[g[k]!=0]["fwd"]*g[g[k]!=0][k]).mean() - g["fwd"].mean()
                               if (g[k]!=0).any() else np.nan)
                a = f(sub)
                parts = sub.groupby("q", observed=True).apply(f)
                bysym = sub.groupby("sym").apply(f).dropna()
                pos = int((bysym > 0).sum())
                ok = (parts > 0).all() and len(bysym) and pos/len(bysym) >= 0.7 and len(sig) >= 100
                print("  %-6s %-6d %+8.0f %6d  %-24s %d/%-5d %s" % (
                    k, h, a, len(sig), " ".join("%+5.0f" % v for v in parts.values),
                    pos, len(bysym), "✅ 통과" if ok else ""))
        print()
