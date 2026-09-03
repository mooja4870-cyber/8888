"""국면 분류기 자체를 시험한다 — 전략을 빼고, 라벨만 놓고 잰다.

왜 여기로 왔나
  port_run.py에서 돈치안은 널과 구분되지 않았다(z=-0.19). 그런데 신호를 통째로 빼고
  '국면 방향만'으로 돌린 대조군 C가 전체기간 +40.7%/y로 전략(+28.9%)을 이겼다.
  최근 2년에는 반대로 +4.3%에 그쳤다. **일하고 있던 건 신호가 아니라 국면 라벨이고,
  그 라벨이 최근에 망가졌을 가능성**이 남는다. 그래서 분류기만 따로 떼어 잰다.

무엇을 재는가 — 전략도 비용도 없이, 라벨의 예측력만
  라벨이 붙은 날의 '그냥 롱 보유' 미래수익을 라벨별로 모은다.
  · BULL 평균 − BEAR 평균  = 방향 분리력. 이게 0이면 국면을 나눌 이유가 없다.
  · BEAR 평균의 **부호**    = 숏의 가능 여부. 암호화폐는 위로 드리프트해서
                              BEAR라도 평균이 양수이기 쉽다. 그러면 '하락장 숏'은
                              원리적으로 불가능하고, 국면은 크기 조절에만 쓸 수 있다.
  · 지속성(평균 연속일수)   = 하루걸러 뒤집히는 라벨은 스위칭 비용으로 죽는다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사전 합격선 — **결과를 보기 전에 확정한다. 사후 완화 금지.**
  ① BULL−BEAR 분리력이 기간 4분할 **전부** 양수
  ② 종목별 분리력 양수 비율 **70% 이상** (10종목 중 7)
  ③ 라벨당 표본 **1,000 종목일 이상**, 평균 연속일수 **5일 이상**
  ④ 분리력이 왕복비용 10bp의 **최소 3배(30bp)** 이상 — 아니면 수확 불가
  ⑤ (숏 사용 조건) BEAR 평균이 음수이고, 기간 4분할 중 **3분기 이상**에서 음수
     — ⑤가 깨지면 숏은 금지하고 국면은 '노출 크기'로만 쓴다
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

모든 분류기는 **i봉까지의 정보로만** 라벨을 만든다(shift(1)). 미래참조 없음.
"""
import numpy as np, pandas as pd
import regime as R
import warnings; warnings.filterwarnings("ignore")

HORIZONS = [5, 10, 20]
MIN_N, MIN_RUN, MIN_SPREAD, MIN_SYM_FRAC = 1000, 5.0, 30.0, 0.70


# ─────────────────────────── 분류기 후보 ───────────────────────────
def _lab(cond_bull, cond_bear, ok):
    out = pd.Series(index=cond_bull.index, dtype=object); out[:] = None
    out[ok & cond_bull] = "BULL"
    out[ok & cond_bear] = "BEAR"
    out[ok & ~cond_bull & ~cond_bear] = "RANGE"
    return out


def clf_adx200(d, btc=None):
    """현행 기준선 — ADX 강도 + 200MA 방향 (regime.classify와 동일)"""
    return R.classify(d)


def clf_ma200_side(d, btc=None):
    """종가가 200MA 위/아래만. ADX 없음 — 횡보를 따로 두지 않는다."""
    ma = d["close"].rolling(200).mean().shift(1); c = d["close"].shift(1)
    ok = ma.notna() & c.notna()
    return _lab(c > ma, c < ma, ok)


def clf_ma200_slope(d, btc=None):
    """200MA '기울기' — 가격 위치가 아니라 추세선 자체가 오르는가."""
    ma = d["close"].rolling(200).mean().shift(1)
    sl = ma.diff(20)
    ok = sl.notna()
    return _lab(sl > 0, sl < 0, ok)


def clf_cross(d, btc=None):
    """골든/데드 크로스 — 50MA vs 200MA"""
    f = d["close"].rolling(50).mean().shift(1); s = d["close"].rolling(200).mean().shift(1)
    ok = f.notna() & s.notna()
    return _lab(f > s, f < s, ok)


def clf_dd(d, btc=None):
    """전고점 대비 낙폭 — 20% 이내면 BULL, 40% 넘게 빠졌으면 BEAR"""
    c = d["close"].shift(1)
    peak = c.cummax()
    dd = c / peak - 1
    ok = c.notna() & (c.index >= 200)
    return _lab(dd > -0.20, dd < -0.40, ok)


def clf_tsmom(d, btc=None):
    """시계열 모멘텀 자체를 국면으로 — 최근 90일 수익 부호"""
    r = d["close"].pct_change(90).shift(1)
    ok = r.notna()
    return _lab(r > 0, r < 0, ok)


def clf_trend_vol(d, btc=None):
    """변동성으로 정규화한 추세 — (50MA−200MA)/ATR. 추세 강도를 연속값으로 본다."""
    f = d["close"].rolling(50).mean(); s = d["close"].rolling(200).mean()
    h, l, c = d["high"], d["low"], d["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    z = ((f - s) / atr).shift(1)
    ok = z.notna()
    return _lab(z > 1.0, z < -1.0, ok)


def clf_btc_market(d, btc=None):
    """시장 전체 국면 — BTC 하나로 판정해 전 종목에 같은 라벨을 붙인다.
    암호화폐는 상관이 높아 종목별 국면이 노이즈일 수 있다는 가설."""
    ma = btc["close"].rolling(200).mean().shift(1); c = btc["close"].shift(1)
    lab = _lab(c > ma, c < ma, ma.notna() & c.notna())
    lab.index = btc["date"].values
    return pd.Series(lab.reindex(d["date"].values).values, index=d.index, dtype=object)


def clf_btc_adx(d, btc=None):
    """시장 전체 국면 + 강도 — BTC의 ADX·200MA를 전 종목에 적용"""
    lab = R.classify(btc)
    lab.index = btc["date"].values
    return pd.Series(lab.reindex(d["date"].values).values, index=d.index, dtype=object)


CLFS = [
    ("현행 ADX+200MA(종목별)", clf_adx200),
    ("200MA 위/아래", clf_ma200_side),
    ("200MA 기울기", clf_ma200_slope),
    ("50/200 크로스", clf_cross),
    ("전고점 낙폭 20/40%", clf_dd),
    ("90일 모멘텀 부호", clf_tsmom),
    ("추세/ATR ±1.0", clf_trend_vol),
    ("BTC 시장국면(200MA)", clf_btc_market),
    ("BTC 시장국면(ADX)", clf_btc_adx),
]


# ─────────────────────────── 측정 ───────────────────────────
def runlen(lab):
    """라벨의 평균 연속일수 — 얼마나 자주 뒤집히는가"""
    s = lab.dropna()
    if s.empty:
        return 0.0
    grp = (s != s.shift()).cumsum()
    return float(s.groupby(grp).size().mean())


def collect():
    btc = R.load("BTC")
    rows = []
    for sym in R.symbols():
        d = R.load(sym)
        op = d["open"].values
        dates = pd.to_datetime(d["date"]).values
        labs = {name: fn(d, btc) for name, fn in CLFS}
        rl = {name: runlen(labs[name]) for name, _ in CLFS}
        fwds = {}
        for h in HORIZONS:
            f = np.full(len(d), np.nan)
            for i in range(len(d) - h - 2):
                e, x = op[i + 1], op[i + 1 + h]
                if e > 0 and x > 0:
                    f[i] = (x / e - 1) * 10000        # 비용 없음 — 라벨의 예측력만 본다
            fwds[h] = f
        for i in range(len(d) - max(HORIZONS) - 2):
            r = {"sym": sym, "date": dates[i]}
            for h in HORIZONS:
                r[f"f{h}"] = fwds[h][i]
            for name, _ in CLFS:
                v = labs[name].iloc[i]
                r[name] = v if isinstance(v, str) else None
            rows.append(r)
    return pd.DataFrame(rows), {name: rl for name, rl in
                                [(n, np.mean([runlen(f(R.load(s), btc)) for s in R.symbols()]))
                                 for n, f in CLFS]}
