"""
볼린저 밴드 돌파(BBTS) — 8410의 라이브 로직을 그대로 재현한 참조 구현.

라이브(core/strategy.py):
    sma   = close.rolling(period).mean()
    std   = close.rolling(period).std()
    upper = sma + std*std_dev ;  lower = sma - std*std_dev
    close > upper → long ;  close < lower → short
    SL = ATR(14) × sl_mult ;  TP = ATR(14) × tp_mult

주의: 라이브는 현재 봉을 포함한 rolling으로 밴드를 만든 뒤 그 봉의 종가와 비교한다.
자기 자신이 밴드에 섞이지만 period=20이면 영향이 작고, **라이브와 같아야** 검증이
의미가 있으므로 그대로 재현한다(임의로 shift 하지 않는다).
성능을 위해 데이터프레임당 한 번만 계산해 캐시한다.
"""
import numpy as np
import pandas as pd


class _Sig:
    __slots__ = ("direction", "atr")

    def __init__(self, direction, atr):
        self.direction, self.atr = direction, atr


class BollingerBreakout:
    def __init__(self, period=20, std_dev=2.0):
        self.p, self.k = period, std_dev
        self.name = f"BB-{period}/{std_dev:g}"
        self._key = None
        self._c = None

    def _build(self, df):
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        sma = close.rolling(self.p).mean()
        std = close.rolling(self.p).std()
        tr = pd.concat([high - low,
                        (high - close.shift(1)).abs(),
                        (low - close.shift(1)).abs()], axis=1).max(axis=1)
        return {
            "c": close.values,
            "up": (sma + std * self.k).values,
            "dn": (sma - std * self.k).values,
            "atr": tr.rolling(14).mean().values,
        }

    def _cache(self, df):
        key = (id(df), len(df))
        if self._key != key:
            self._key = key
            self._c = self._build(df)
        return self._c

    def at(self, df, i):
        d = self._cache(df)
        c, up, dn, a = d["c"][i], d["up"][i], d["dn"][i], d["atr"][i]
        if not (np.isfinite(up) and np.isfinite(dn) and np.isfinite(a)) or a <= 0:
            return None
        if c > up:
            return _Sig("long", float(a))
        if c < dn:
            return _Sig("short", float(a))
        return None


class KeltnerBreakout:
    """켈트너 채널 돌파 — EMA ± ATR×k. 변동성 추정을 표준편차가 아닌 ATR로 한다.

    문헌: 볼린저(표준편차)와 켈트너(ATR)의 차이는 변동성 급변 구간에서 크게 벌어진다.
    같은 '돌파' 계열이라도 밴드 산출 방식이 달라 신호 타이밍이 어긋나므로,
    분산 관점에서 별도 후보로 시험한다.
    """

    def __init__(self, period=20, mult=2.0):
        self.p, self.k = period, mult
        self.name = f"KC-{period}/{mult:g}"
        self._key = None
        self._c = None

    def _build(self, df):
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        ema = close.ewm(span=self.p, adjust=False).mean()
        tr = pd.concat([high - low,
                        (high - close.shift(1)).abs(),
                        (low - close.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        return {"c": close.values,
                "up": (ema + atr * self.k).values,
                "dn": (ema - atr * self.k).values,
                "atr": atr.values}

    def _cache(self, df):
        key = (id(df), len(df))
        if self._key != key:
            self._key = key
            self._c = self._build(df)
        return self._c

    def at(self, df, i):
        d = self._cache(df)
        c, up, dn, a = d["c"][i], d["up"][i], d["dn"][i], d["atr"][i]
        if not (np.isfinite(up) and np.isfinite(dn) and np.isfinite(a)) or a <= 0:
            return None
        if c > up:
            return _Sig("long", float(a))
        if c < dn:
            return _Sig("short", float(a))
        return None
