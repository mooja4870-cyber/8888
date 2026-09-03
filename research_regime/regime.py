"""국면 분류기 — 200일선 방향 + ADX 추세강도로 3분할.

문헌 근거
  · sparse jump model (Digital Finance 2023): 암호화폐는 상승·하락·횡보 3국면으로 갈리고
    시계열 모멘텀이 핵심 동인이다.
  · 200일선은 '방향'만, ADX는 '추세 강도'만 알려준다. 200일선만 쓰면 강한 하락추세를
    횡보로 오인한다. 둘을 함께 써야 3국면이 제대로 갈린다.

분류 (빠짐없이·겹치지 않게)
  ADX < ADX_TH            → 횡보(RANGE)
  ADX ≥ ADX_TH & 종가>200MA → 상승추세(BULL)
  ADX ≥ ADX_TH & 종가<200MA → 하락추세(BEAR)

국면은 **직전 봉까지의 정보만으로** 판정한다(현재 봉 제외). 그래야 미래참조가 없다.
"""
import glob, os
import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load(sym: str) -> pd.DataFrame:
    d = pd.read_csv(os.path.join(DATA, f"{sym}.csv"))
    d["date"] = pd.to_datetime(d["date"])
    return d.sort_values("ts").reset_index(drop=True)


def symbols():
    return sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(DATA, "*.csv")))


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def classify(df: pd.DataFrame, ma_len: int = 200, adx_th: float = 20.0,
             adx_len: int = 14) -> pd.Series:
    ma = df["close"].rolling(ma_len).mean()
    a = adx(df, adx_len)
    # 직전 봉 기준 — 현재 봉 정보를 쓰지 않는다
    c_prev, ma_prev, a_prev = df["close"].shift(1), ma.shift(1), a.shift(1)
    out = pd.Series(index=df.index, dtype=object)
    out[:] = None
    ok = c_prev.notna() & ma_prev.notna() & a_prev.notna()
    out[ok & (a_prev < adx_th)] = "RANGE"
    out[ok & (a_prev >= adx_th) & (c_prev > ma_prev)] = "BULL"
    out[ok & (a_prev >= adx_th) & (c_prev <= ma_prev)] = "BEAR"
    return out
