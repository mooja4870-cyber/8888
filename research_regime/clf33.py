"""33종목 실거래 종목군으로 국면 분류기·돌파 신호를 재검증한다.

왜 다시 재나
  종전 검증은 메이저 10종목(BTC·ETH·SOL·BNB·XRP·ADA·DOGE·LINK·LTC·AVAX)으로 했는데
  8402가 실제로 매매할 종목군과 겹치지 않았다. "검증 종목군 = 실거래 종목군"이 아니면
  결과를 해석할 수 없다.

  이번 종목군은 8402 화이트리스트 33개 그대로다(거래대금·스프레드·최소주문·상장기간 필터 통과).
  국면 판정 기준은 BTC 일봉으로 동일하다.

주의: 상장 기간이 짧은 종목이 섞여 있다(DASH 303봉 ~ ETH 1500봉).
200일선 워밍업을 빼면 종목별 유효 표본이 크게 다르므로 종목 수를 함께 본다.
"""
import os, glob
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data33")
COST_BP = 10.0


def load(sym):
    d = pd.read_csv(os.path.join(DATA, f"{sym}.csv"))
    d["date"] = pd.to_datetime(d["date"])
    return d.sort_values("ts").reset_index(drop=True)


def symbols():
    return sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(DATA, "*.csv"))
                  if os.path.basename(f)[:-4] != "BTC")


def adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    p = np.where((up > dn) & (up > 0), up, 0.0)
    m = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/n, adjust=False).mean()
    pdi = 100 * pd.Series(p, index=df.index).ewm(alpha=1/n, adjust=False).mean() / atr
    mdi = 100 * pd.Series(m, index=df.index).ewm(alpha=1/n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean()


def btc_regime(ma_len=200, th=20.0):
    """BTC 일봉 하나로 시장 국면 — 8402 라우터와 동일한 규칙"""
    b = load("BTC")
    ma = b["close"].rolling(ma_len).mean().shift(1)
    a = adx(b, 14).shift(1)
    c = b["close"].shift(1)
    lab = pd.Series(index=b.index, dtype=object); lab[:] = None
    ok = ma.notna() & a.notna() & c.notna()
    lab[ok & (a < th)] = "RANGE"
    lab[ok & (a >= th) & (c > ma)] = "BULL"
    lab[ok & (a >= th) & (c <= ma)] = "BEAR"
    return pd.Series(lab.values, index=b["date"].values, dtype=object)


def sig_donchian(d, n=55):
    hi = d["high"].rolling(n).max().shift(1)
    lo = d["low"].rolling(n).min().shift(1)
    s = pd.Series(0, index=d.index)
    s[d["close"] > hi] = 1
    s[d["close"] < lo] = -1
    return s


HOLDS = {"BULL": 20, "BEAR": 5, "RANGE": 10}


def run():
    reg = btc_regime()
    rows = []
    for sym in symbols():
        d = load(sym)
        if len(d) < 120:
            continue
        op = d["open"].values
        dates = pd.to_datetime(d["date"]).values
        r = np.array([reg.get(x, None) for x in dates], dtype=object)
        sig = sig_donchian(d, 55).values
        volok = (d["volume"] > d["volume"].rolling(20).mean()).fillna(False).values
        for h in set(HOLDS.values()):
            fwd = np.full(len(d), np.nan)
            for i in range(len(d) - h - 2):
                e, x = op[i+1], op[i+1+h]
                if e > 0 and x > 0:
                    fwd[i] = (x/e - 1) * 10000 - COST_BP
            for i in range(len(d) - h - 2):
                if r[i] is None or not np.isfinite(fwd[i]):
                    continue
                rows.append(dict(sym=sym, regime=r[i], h=h, date=dates[i+1],
                                 fwd=fwd[i], sig=sig[i],
                                 sigv=sig[i] if volok[i] else 0))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = run()
    print("8402 실거래 33종목 재검증 — 국면 판정=BTC 일봉 · 비관비용 왕복 10bp\n")
    print("  표본: %d종목 · %s ~ %s\n" % (df["sym"].nunique(),
          str(df["date"].min())[:10], str(df["date"].max())[:10]))
    print("  %-6s %-4s %-8s %9s %7s  %-26s %-8s %s" %
          ("국면", "보유", "신호", "알파bp", "건수", "기간4분할", "흑자종목", "판정"))
    for rg, h in HOLDS.items():
        sub = df[(df["regime"] == rg) & (df["h"] == h)].copy()
        if sub.empty:
            print("  %-6s %-4d 표본 없음" % (rg, h)); continue
        sub["q"] = pd.qcut(sub["date"].astype("int64"), 4, labels=list("1234"))
        for col, nm in (("sig", "돌파"), ("sigv", "돌파+거래량")):
            f = lambda g: ((g[g[col] != 0]["fwd"] * g[g[col] != 0][col]).mean() - g["fwd"].mean()
                           if (g[col] != 0).any() else np.nan)
            a = f(sub)
            parts = sub.groupby("q", observed=True).apply(f)
            bysym = sub.groupby("sym").apply(f).dropna()
            pos = int((bysym > 0).sum())
            n = int((sub[col] != 0).sum())
            ok = (parts > 0).all() and len(bysym) and pos/len(bysym) >= 0.7 and n >= 100
            print("  %-6s %-4d %-8s %+9.0f %7d  %-26s %2d/%-5d %s" % (
                rg, h, nm, a, n, " ".join("%+6.0f" % v for v in parts.values),
                pos, len(bysym), "✅ 통과" if ok else ""))


# ── 더블 볼린저 검증 (현재 하락장에 배정된 전략) ───────────────────────────
def sig_dbb(d, n=20, k1=1.0, k2=2.0):
    """8402 DualBBStrategy와 같은 규칙: +1SD~+2SD 롱 / -2SD~-1SD 숏, 그 밖은 관망"""
    c = d["close"]; m = c.rolling(n).mean(); sd = c.rolling(n).std()
    u1, l1, u2, l2 = m + k1*sd, m - k1*sd, m + k2*sd, m - k2*sd
    s = pd.Series(0, index=d.index)
    s[(c > u1) & (c <= u2)] = 1
    s[(c < l1) & (c >= l2)] = -1
    return s


def run_dbb():
    reg = btc_regime(); rows = []
    for sym in symbols():
        d = load(sym)
        if len(d) < 120: continue
        op = d["open"].values; dates = pd.to_datetime(d["date"]).values
        r = np.array([reg.get(x, None) for x in dates], dtype=object)
        s = sig_dbb(d).values
        for h in (5, 10, 20):
            fwd = np.full(len(d), np.nan)
            for i in range(len(d)-h-2):
                e, x = op[i+1], op[i+1+h]
                if e > 0 and x > 0: fwd[i] = (x/e-1)*10000 - COST_BP
            for i in range(len(d)-h-2):
                if r[i] is None or not np.isfinite(fwd[i]): continue
                rows.append(dict(sym=sym, regime=r[i], h=h, date=dates[i+1], fwd=fwd[i], sig=s[i]))
    return pd.DataFrame(rows)
