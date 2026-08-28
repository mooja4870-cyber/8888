"""
역추세(평균회귀) 신호 후보군.

8408은 함대에서 유일한 역추세 봇이다. 8407·8409(일봉 돈치안 돌파)와
8410(4시간봉 볼린저 돌파)이 모두 추세추종이므로, 역추세가 성립하기만 하면
분산 효과가 크다. 그래서 한 구현(DualBB)만 보고 접지 않고 계열 전체를 훑는다.

문헌 근거 — 모멘텀과 평균회귀는 국면 보완적이며, 두 알파를 함께 굴리면
개별 전략보다 매끄러운 수익을 낸다(Systematic Crypto Trading Strategies:
모멘텀 Sharpe 1.0 / BTC중립 잔차 평균회귀 2.3 / 50:50 혼합 1.71).

모든 신호는 .at(df, i) → (direction, atr) 인터페이스를 지킨다.
데이터프레임당 한 번 벡터 계산해 캐시한다.
"""
import numpy as np
import pandas as pd


class _Sig:
    __slots__ = ("direction", "atr")

    def __init__(self, direction, atr):
        self.direction, self.atr = direction, atr


class _Base:
    def __init__(self):
        self._key = None
        self._c = None

    def _cache(self, df):
        key = (id(df), len(df))
        if self._key != key:
            self._key = key
            self._c = self._build(df)
        return self._c

    @staticmethod
    def _atr(df, period=14):
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        c = df["close"].astype(float)
        tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean().values


class BandReversion(_Base):
    """볼린저 밴드 이탈 → 되돌림. 돌파의 정반대 방향으로 진입한다.

    상단 이탈이면 숏, 하단 이탈이면 롱. 8408 DualBB의 3단계 확인 없이
    단순 이탈만 보는 형태로, 계열의 기본형을 대표한다.
    """

    def __init__(self, period=20, k=2.0):
        super().__init__()
        self.p, self.k = period, k
        self.name = f"MR-BB-{period}/{k:g}"

    def _build(self, df):
        c = df["close"].astype(float)
        sma = c.rolling(self.p).mean()
        sd = c.rolling(self.p).std()
        return {"c": c.values, "up": (sma + sd * self.k).values,
                "dn": (sma - sd * self.k).values, "atr": self._atr(df)}

    def at(self, df, i):
        d = self._cache(df)
        c, up, dn, a = d["c"][i], d["up"][i], d["dn"][i], d["atr"][i]
        if not (np.isfinite(up) and np.isfinite(dn) and np.isfinite(a)) or a <= 0:
            return None
        if c > up:
            return _Sig("short", float(a))
        if c < dn:
            return _Sig("long", float(a))
        return None


class BandReturn(_Base):
    """이탈 후 **밴드 안으로 복귀한 봉**에서 진입 — DualBB의 핵심 아이디어를 단순화.

    이탈만 보고 들어가면 추세가 이어질 때 계속 물린다. 복귀를 확인하면
    '되돌림이 실제로 시작된 뒤'에만 들어가므로 그 위험이 준다.
    """

    def __init__(self, period=20, k=2.5):
        super().__init__()
        self.p, self.k = period, k
        self.name = f"MR-RET-{period}/{k:g}"

    def _build(self, df):
        c = df["close"].astype(float)
        sma = c.rolling(self.p).mean()
        sd = c.rolling(self.p).std()
        return {"c": c.values, "up": (sma + sd * self.k).values,
                "dn": (sma - sd * self.k).values, "atr": self._atr(df)}

    def at(self, df, i):
        if i < 1:
            return None
        d = self._cache(df)
        c0, c1 = d["c"][i - 1], d["c"][i]
        up0, dn0 = d["up"][i - 1], d["dn"][i - 1]
        up1, dn1 = d["up"][i], d["dn"][i]
        a = d["atr"][i]
        if not (np.isfinite(up0) and np.isfinite(dn0) and np.isfinite(a)) or a <= 0:
            return None
        # 직전 봉이 밴드 밖 → 이번 봉이 안으로 복귀
        if c0 > up0 and c1 <= up1:
            return _Sig("short", float(a))
        if c0 < dn0 and c1 >= dn1:
            return _Sig("long", float(a))
        return None


class RsiReversion(_Base):
    """RSI 과매수/과매도 극단에서의 되돌림."""

    def __init__(self, period=14, lo=25, hi=75):
        super().__init__()
        self.p, self.lo, self.hi = period, lo, hi
        self.name = f"MR-RSI-{period}/{lo}-{hi}"

    def _build(self, df):
        c = df["close"].astype(float)
        d = c.diff()
        up = d.clip(lower=0).ewm(alpha=1 / self.p, adjust=False).mean()
        dn = (-d.clip(upper=0)).ewm(alpha=1 / self.p, adjust=False).mean()
        rs = up / dn.replace(0, np.nan)
        return {"rsi": (100 - 100 / (1 + rs)).values, "atr": self._atr(df)}

    def at(self, df, i):
        d = self._cache(df)
        r, a = d["rsi"][i], d["atr"][i]
        if not (np.isfinite(r) and np.isfinite(a)) or a <= 0:
            return None
        if r >= self.hi:
            return _Sig("short", float(a))
        if r <= self.lo:
            return _Sig("long", float(a))
        return None


def candidates():
    out = []
    for p in (10, 20, 30):
        for k in (2.0, 2.5, 3.0):
            out.append(BandReversion(p, k))
            out.append(BandReturn(p, k))
    for lo, hi in ((20, 80), (25, 75), (30, 70)):
        out.append(RsiReversion(14, lo, hi))
    return out
