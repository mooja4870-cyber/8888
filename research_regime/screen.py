"""국면별 전략 스크리닝 — 신호가 국면마다 실제로 엣지가 있는지 잰다.

방법
  · 신호는 i봉까지의 정보로만 만들고, 진입은 i+1봉 시가, 청산은 i+1+h봉 시가.
    (미래참조 없음. 종가에 신호 내고 그 종가에 사는 백테스트는 실현 불가능하다.)
  · 국면은 직전 봉 기준으로 이미 정해져 있다.
  · 비용은 비관적으로 전량 테이커 왕복 10bp(0.05% × 2).
  · 손절/익절은 두지 않는다 — 이 단계는 '신호 자체에 엣지가 있는가'만 가린다.
    출구 설계는 엣지를 확인한 뒤에 붙인다.
"""
import numpy as np, pandas as pd
import regime as R

COST_BP = 10.0


def sig_donchian(d, n):
    hi = d["high"].rolling(n).max().shift(1)
    lo = d["low"].rolling(n).min().shift(1)
    s = pd.Series(0, index=d.index)
    s[d["close"] > hi] = 1
    s[d["close"] < lo] = -1
    return s


def sig_tsmom(d, n):
    r = d["close"].pct_change(n)
    return pd.Series(np.sign(r).fillna(0).astype(int), index=d.index)


def sig_bb_revert(d, n=20, k=2.0):
    m = d["close"].rolling(n).mean(); sd = d["close"].rolling(n).std()
    s = pd.Series(0, index=d.index)
    s[d["close"] > m + k * sd] = -1      # 상단 이탈 → 하락 반전 기대
    s[d["close"] < m - k * sd] = 1
    return s


def sig_rsi2(d, lo=10, hi=90, n=2):
    ch = d["close"].diff()
    up = ch.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-ch.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    s = pd.Series(0, index=d.index)
    s[rsi < lo] = 1
    s[rsi > hi] = -1
    return s


def sig_zscore(d, n=20, k=2.0):
    m = d["close"].rolling(n).mean(); sd = d["close"].rolling(n).std()
    z = (d["close"] - m) / sd
    s = pd.Series(0, index=d.index)
    s[z > k] = -1
    s[z < -k] = 1
    return s


CANDS = [
    ("모멘텀 Donchian-20", lambda d: sig_donchian(d, 20)),
    ("모멘텀 Donchian-55", lambda d: sig_donchian(d, 55)),
    ("모멘텀 TSMOM-20",    lambda d: sig_tsmom(d, 20)),
    ("모멘텀 TSMOM-60",    lambda d: sig_tsmom(d, 60)),
    ("반전 볼린저-20/2",   lambda d: sig_bb_revert(d, 20, 2.0)),
    ("반전 RSI2-10/90",    lambda d: sig_rsi2(d)),
    ("반전 Z-20/2",        lambda d: sig_zscore(d, 20, 2.0)),
]
HOLDS = [5, 10, 20]


def run():
    recs = []
    for sym in R.symbols():
        d = R.load(sym)
        reg = R.classify(d)
        op = d["open"].values
        for name, fn in CANDS:
            s = fn(d).values
            for h in HOLDS:
                for i in range(len(d) - h - 2):
                    if s[i] == 0 or reg.iloc[i] is None:
                        continue
                    e, x = op[i + 1], op[i + 1 + h]
                    if not (e > 0 and x > 0):
                        continue
                    ret = (x / e - 1) * s[i] * 10000 - COST_BP     # bp
                    recs.append((name, h, reg.iloc[i], ret))
    return pd.DataFrame(recs, columns=["strategy", "hold", "regime", "bp"])


if __name__ == "__main__":
    df = run()
    print("6~7년 · 10종목 · 일봉 · 비관비용 전량테이커 왕복 10bp", flush=True)
    print("숫자 = 건당 순엣지(bp). 양수라야 비용을 넘긴 것.\n", flush=True)
    for h in HOLDS:
        sub = df[df["hold"] == h]
        piv = sub.pivot_table(index="strategy", columns="regime", values="bp", aggfunc="mean")
        cnt = sub.pivot_table(index="strategy", columns="regime", values="bp", aggfunc="size")
        print(f"── 보유 {h}일 ──")
        for st in piv.index:
            cells = " ".join(f"{r} {piv.loc[st, r]:+7.1f}bp({int(cnt.loc[st, r]):>5})"
                             for r in ("BULL", "BEAR", "RANGE") if r in piv.columns)
            print(f"  {st:<20} {cells}")
        print()
