"""
8407 신호 후보군 — 기저 신호 교체를 위한 탐색.

현행 core/strategy.py 의 predict_direction 은
    score = ret_1*0.4 + ret_5*0.6 ;  prob = sigmoid(score*100)
즉 15분·75분 지평의 초단기 모멘텀이다. 이 지평에서 암호자산 수익률은
마이크로구조 노이즈가 지배해 방향 예측력이 사실상 없다(기간분할에서 확인).

시계열 모멘텀 문헌은 훨씬 긴 지평에서 성립한다고 보고한다.
따라서 '지평을 늘리면 살아나는가'를 먼저 시험한다.

성능: 봉마다 전체를 재계산하면 O(n²)라 90일치에서 감당이 안 된다.
      데이터프레임별로 한 번 벡터 계산해 캐시하고, at(i)는 O(1)로 읽는다.
      캐시는 id(df)로 키를 잡되 길이를 함께 검증해 오염을 막는다.
"""
import numpy as np


def _true_range(h, l, c):
    tr = np.empty(len(c), dtype=float)
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum(h[1:] - l[1:], np.abs(h[1:] - c[:-1]))
    return tr


def _atr_series(df, period=14):
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    tr = _true_range(h, l, c)
    out = np.full(len(c), np.nan)
    if len(c) >= period:
        csum = np.cumsum(tr)
        out[period - 1:] = (csum[period - 1:] - np.concatenate(([0.0], csum[:-period]))) / period
    return out


def _ema_series(x, p):
    k = 2.0 / (p + 1.0)
    e = np.empty(len(x), dtype=float)
    e[0] = x[0]
    for j in range(1, len(x)):
        e[j] = x[j] * k + e[j - 1] * (1 - k)
    return e


def _rolling_std_log(c, win):
    lr = np.diff(np.log(c), prepend=np.log(c[0]))
    s = np.full(len(c), np.nan)
    cs = np.cumsum(lr)
    cs2 = np.cumsum(lr * lr)
    for i in range(win, len(c)):
        n = win
        m = (cs[i] - cs[i - win]) / n
        v = (cs2[i] - cs2[i - win]) / n - m * m
        s[i] = np.sqrt(max(v, 0.0))
    return s


class _Sig:
    __slots__ = ("direction", "atr")

    def __init__(self, direction, atr):
        self.direction, self.atr = direction, atr


class _Base:
    """id(df) 기반 캐시. 길이를 함께 저장해 다른 조각과 섞이지 않게 한다."""

    def __init__(self):
        self._key = None
        self._c = None

    def _cache(self, df):
        key = (id(df), len(df))
        if self._key != key:
            self._key = key
            self._c = self._build(df)
        return self._c


class Momentum(_Base):
    """시계열 모멘텀 — N봉 수익률의 부호. 15분봉 기준 4=1시간, 96=1일."""

    def __init__(self, lookback):
        super().__init__()
        self.n = lookback
        self.name = f"MOM-{lookback}"

    def _build(self, df):
        c = df["close"].values.astype(float)
        r = np.full(len(c), np.nan)
        if len(c) > self.n:
            r[self.n:] = c[self.n:] / c[:-self.n] - 1.0
        return {"r": r, "atr": _atr_series(df)}

    def at(self, df, i):
        d = self._cache(df)
        r, a = d["r"][i], d["atr"][i]
        if not np.isfinite(r) or not np.isfinite(a) or a <= 0 or r == 0:
            return None
        return _Sig("long" if r > 0 else "short", float(a))


class MomentumVolFilter(_Base):
    """모멘텀 + 변동성 필터.

    문헌: 변동성 필터를 얹은 모멘텀이 순수 모멘텀보다 Sharpe가 높다
    (Systematic Crypto Trading Strategies: 1.0 → 1.2).
    최근/장기 변동성 비율이 임계를 넘는 과열 구간에서는 진입하지 않는다.
    """

    def __init__(self, lookback, vol_max=1.8):
        super().__init__()
        self.n, self.vmax = lookback, vol_max
        self.name = f"MOMVOL-{lookback}"

    def _build(self, df):
        c = df["close"].values.astype(float)
        r = np.full(len(c), np.nan)
        if len(c) > self.n:
            r[self.n:] = c[self.n:] / c[:-self.n] - 1.0
        return {"r": r, "atr": _atr_series(df),
                "v20": _rolling_std_log(c, 20), "v100": _rolling_std_log(c, 100)}

    def at(self, df, i):
        d = self._cache(df)
        r, a = d["r"][i], d["atr"][i]
        v20, v100 = d["v20"][i], d["v100"][i]
        if not np.isfinite(r) or not np.isfinite(a) or a <= 0 or r == 0:
            return None
        if not np.isfinite(v20) or not np.isfinite(v100) or v100 <= 0:
            return None
        if v20 / v100 > self.vmax:
            return None
        return _Sig("long" if r > 0 else "short", float(a))


class EmaCross(_Base):
    """EMA 정배열/역배열 — 고전적 추세 추종."""

    def __init__(self, fast, slow):
        super().__init__()
        self.f, self.s = fast, slow
        self.name = f"EMA-{fast}/{slow}"

    def _build(self, df):
        c = df["close"].values.astype(float)
        return {"ef": _ema_series(c, self.f), "es": _ema_series(c, self.s),
                "atr": _atr_series(df)}

    def at(self, df, i):
        if i < self.s:
            return None
        d = self._cache(df)
        ef, es, a = d["ef"][i], d["es"][i], d["atr"][i]
        if not np.isfinite(a) or a <= 0 or ef == es:
            return None
        return _Sig("long" if ef > es else "short", float(a))


class Donchian(_Base):
    """돈치안 채널 돌파 — 8404가 쓰는 계열."""

    def __init__(self, lookback):
        super().__init__()
        self.n = lookback
        self.name = f"DON-{lookback}"

    def _build(self, df):
        import pandas as pd
        h = pd.Series(df["high"].values.astype(float))
        l = pd.Series(df["low"].values.astype(float))
        # i 시점 판정에 i 자신을 넣으면 자기 돌파가 되므로 한 칸 민다
        return {"hh": h.rolling(self.n).max().shift(1).values,
                "ll": l.rolling(self.n).min().shift(1).values,
                "atr": _atr_series(df)}

    def at(self, df, i):
        d = self._cache(df)
        hh, ll, a = d["hh"][i], d["ll"][i], d["atr"][i]
        if not np.isfinite(hh) or not np.isfinite(ll) or not np.isfinite(a) or a <= 0:
            return None
        c = float(df["close"].values[i])
        if c > hh:
            return _Sig("long", float(a))
        if c < ll:
            return _Sig("short", float(a))
        return None


def candidates():
    """파라미터를 촘촘히 훑어 '이웃 값에서도 성립하는가'를 본다."""
    out = []
    for n in (4, 12, 24, 48, 96, 192, 384):
        out.append(Momentum(n))
    for n in (24, 48, 96, 192):
        out.append(MomentumVolFilter(n))
    for f, s in ((9, 21), (12, 48), (24, 96), (48, 192)):
        out.append(EmaCross(f, s))
    for n in (24, 48, 96, 192):
        out.append(Donchian(n))
    return out
