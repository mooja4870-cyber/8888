"""하락장·횡보장 후보 검증 — 문헌에서 뽑은 필터를 붙여 알파가 생기는지 본다.

후보
  A 돌파 (기준선)                     : Donchian-55 양방향
  B 방향 제한                         : 상승장 롱만 / 하락장 숏만
  C 스퀴즈 돌파                       : BB밴드폭 하위30% & ATR<ATR평균 일 때만
  D 거래량 확인                       : 돌파봉 거래량 > 20일 평균
  E RSI 확인                          : 롱 RSI>55 / 숏 RSI<45
  F 스퀴즈+거래량                     : C와 D 동시

알파 = (신호일 평균수익 × 방향) − (그 구간 모든 날 무조건롱 평균수익)
비용 전량 테이커 왕복 10bp. 보유 20일. 미래참조 없음(신호 i봉, 진입 i+1 시가).
"""
import numpy as np, pandas as pd
import regime as R
from screen import sig_donchian, COST_BP
import warnings; warnings.filterwarnings("ignore")

HOLD, N = 20, 55


def feats(d):
    c, h, l, v = d["close"], d["high"], d["low"], d["volume"]
    m, sd = c.rolling(20).mean(), c.rolling(20).std()
    bw = (4 * sd / m)                                   # 밴드폭
    bw_pct = bw.rolling(180).rank(pct=True)             # 최근 6개월 내 백분위
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    ch = c.diff()
    up = ch.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    dn = (-ch.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return dict(squeeze=(bw_pct < 0.30) & (atr < atr.rolling(20).mean()),
                volok=v > v.rolling(20).mean(), rsi=rsi)


def build(d, reg):
    s = sig_donchian(d, N)
    f = feats(d)
    out = {}
    out["A 돌파(양방향)"] = s.copy()
    b = s.copy()
    b[(reg == "BULL") & (s < 0)] = 0
    b[(reg == "BEAR") & (s > 0)] = 0
    out["B 방향제한"] = b
    out["C 스퀴즈"] = s.where(f["squeeze"].fillna(False), 0)
    out["D 거래량"] = s.where(f["volok"].fillna(False), 0)
    e = s.copy()
    e[(s > 0) & ~(f["rsi"] > 55)] = 0
    e[(s < 0) & ~(f["rsi"] < 45)] = 0
    out["E RSI확인"] = e
    out["F 스퀴즈+거래량"] = s.where((f["squeeze"] & f["volok"]).fillna(False), 0)
    return out


def run():
    rows = []
    for sym in R.symbols():
        d = R.load(sym); reg = R.classify(d); op = d["open"].values
        dates = pd.to_datetime(d["date"]).values
        fwd = np.full(len(d), np.nan)
        for i in range(len(d) - HOLD - 2):
            e, x = op[i + 1], op[i + 1 + HOLD]
            if e > 0 and x > 0:
                fwd[i] = (x / e - 1) * 10000 - COST_BP
        cands = build(d, reg)
        for i in range(len(d) - HOLD - 2):
            if reg.iloc[i] is None or not np.isfinite(fwd[i]):
                continue
            r = {"sym": sym, "regime": reg.iloc[i], "date": dates[i + 1], "fwd": fwd[i]}
            for k, v in cands.items():
                r[k] = v.iloc[i]
            rows.append(r)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = run()
    df["q"] = pd.qcut(df["date"].astype("int64"), 4, labels=list("1234"))
    names = [c for c in df.columns if c[0] in "ABCDEF" and " " in c]
    print("하락장·횡보장 후보 — 알파(bp) · 보유 %d일 · Donchian-%d 기반\n" % (HOLD, N), flush=True)
    for r in ("BEAR", "RANGE", "BULL"):
        sub = df[df["regime"] == r]
        print("── %s ──" % r)
        print("  %-18s %8s %6s  %-26s %-8s %s" % ("후보", "알파", "건수", "기간4분할", "흑자종목", "판정"))
        for k in names:
            sig = sub[sub[k] != 0]
            if len(sig) < 20: 
                print("  %-18s %8s %6d  (표본부족)" % (k, "-", len(sig))); continue
            f = lambda g: ((g[g[k] != 0]["fwd"] * g[g[k] != 0][k]).mean() - g["fwd"].mean()
                           if (g[k] != 0).any() else np.nan)
            a = f(sub)
            parts = sub.groupby("q", observed=True).apply(f)
            bysym = sub.groupby("sym").apply(f).dropna()
            pos = int((bysym > 0).sum())
            ok = (parts > 0).all() and len(bysym) and pos / len(bysym) >= 0.7 and len(sig) >= 100
            print("  %-18s %+8.0f %6d  %-26s %d/%-6d %s" % (
                k, a, len(sig), " ".join("%+5.0f" % v for v in parts.values),
                pos, len(bysym), "✅ 통과" if ok else ""))
        print()
