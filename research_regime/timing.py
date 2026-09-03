"""시장국면 타이밍 오버레이 — 종목을 고르지 말고, '언제 시장에 있을지'만 정한다.

여기까지 온 경로
  · 돈치안의 종목 선택은 널과 동률이었다(port_run.py 널A z=-0.19). 종목은 못 고른다.
  · 분류기만 떼어 재니(clf_run.py) **BTC 하나로 시장 전체를 판정한 라벨**이 보유 5·10·20일
    전부에서 사전 합격선 ①②③④를 통과했다. 종목별 국면은 노이즈였다.
  · 그러나 ⑤(숏 조건)는 전 분류기가 실패했다. BEAR 평균은 분기마다 부호가 뒤집힌다.
    → **숏은 금지. 국면은 방향이 아니라 '노출 크기'만 정한다.**

그래서 시험 대상은 이 형태가 된다
  BTC의 ADX+200MA가 BULL  → 10종목 균등 롱, 정상 노출
  그 외(BEAR·RANGE)        → 관망(또는 축소 노출)

종목 선택이 없으므로 신호도 없다. 남은 질문은 하나다 — **시장에 들어가 있는 날을 고르는
그 선택에 값이 있는가.** 이건 널로만 갈린다.

널 설계 — 블록 부트스트랩
  단순히 날짜를 무작위로 흩뿌리면 안 된다. 실제 국면은 평균 17일씩 뭉쳐 있어서,
  뭉침 자체가 수익률에 영향을 준다. 그래서 **실제와 같은 개수·같은 길이의 구간을**
  달력 위 무작위 위치에 다시 깔아 200회 돌린다. 보존되는 것은 시장체류일수와 뭉침 구조,
  달라지는 것은 '어느 구간에 있었나'뿐이다.
"""
import numpy as np, pandas as pd
import regime as R
import warnings; warnings.filterwarnings("ignore")

COST_BP = 10.0          # 국면 전환 1회당 왕복 (전량 테이커, 비관)
INIT = 10000.0


def market_regime(kind="adx"):
    """BTC 한 종목으로 시장 국면을 판정해 달력 전체에 붙인다."""
    btc = R.load("BTC")
    if kind == "adx":
        lab = R.classify(btc)
    else:
        ma = btc["close"].rolling(200).mean().shift(1); c = btc["close"].shift(1)
        lab = pd.Series(index=btc.index, dtype=object); lab[:] = None
        ok = ma.notna() & c.notna()
        lab[ok & (c > ma)] = "BULL"
        lab[ok & (c <= ma)] = "BEAR"
    return pd.Series(lab.values, index=pd.to_datetime(btc["date"]).values, dtype=object)


def basket():
    """10종목 균등비중 일일 수익률 — 시가 대 시가."""
    per = {}
    for s in R.symbols():
        d = R.load(s)
        per[s] = pd.Series(d["open"].values, index=pd.to_datetime(d["date"]).values)
    cal = pd.DatetimeIndex(sorted(set().union(*(p.index for p in per.values()))))
    px = pd.DataFrame({s: p.reindex(cal) for s, p in per.items()})
    return cal, px.pct_change().mean(axis=1).fillna(0.0).values


def runs_of(mask):
    """True 구간들의 (시작, 길이) 목록"""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append((i, j - i)); i = j
        else:
            i += 1
    return out


def tradable(mask):
    """라벨을 실제로 체결 가능한 시점에 맞춘다 — **미래참조 차단**.

    rets[i]는 open[i-1] → open[i] 구간 수익이다. 그 구간을 먹으려면 open[i-1]에
    이미 포지션이 있어야 하고, 그때 알 수 있는 국면은 close[i-2]로 만든 라벨,
    즉 배열 인덱스 i-1이다. 그대로 mask[i]와 rets[i]를 짝지으면 close[i-1]로
    open[i-1]부터의 수익을 먹는 셈이라 반나절을 훔친다.
    """
    out = np.zeros(len(mask), bool)
    out[1:] = mask[:-1]
    return out


def equity(rets, mask, expo_in, expo_out):
    """마스크에 따라 노출을 바꿔 자산곡선을 만든다. 노출이 바뀌는 날 왕복비용을 문다."""
    e = INIT; curve = np.empty(len(rets)); prev = expo_out
    for i, r in enumerate(rets):
        x = expo_in if mask[i] else expo_out
        if x != prev:
            e *= 1 - COST_BP / 10000.0 * max(x, prev)
        e *= 1 + r * x
        prev = x
        curve[i] = e
    return curve


def stats(e, cal):
    yrs = (cal[-1] - cal[0]).days / 365.25
    cagr = (e[-1] / e[0]) ** (1 / yrs) - 1 if yrs > 0 and e[-1] > 0 else -1.0
    mdd = float(np.min(e / np.maximum.accumulate(e)) - 1)
    dr = np.diff(e) / e[:-1]
    sh = float(np.mean(dr) / np.std(dr) * np.sqrt(365)) if np.std(dr) > 0 else 0.0
    return dict(ret=e[-1] / e[0] - 1, cagr=cagr, mdd=mdd, sharpe=sh)


def quarters(e, k=4):
    idx = np.linspace(0, len(e) - 1, k + 1).astype(int)
    return [e[idx[j + 1]] / e[idx[j]] - 1 for j in range(k)]


def null_masks(mask, rng, n_try=200):
    """실제와 같은 개수·같은 길이의 구간을 무작위 위치에 다시 깐다."""
    N = len(mask)
    lens = [l for _, l in runs_of(mask)]
    out = np.zeros(N, bool)
    for L in sorted(lens, reverse=True):
        for _ in range(n_try):
            s = rng.integers(0, max(1, N - L))
            if not out[s:s + L].any():
                out[s:s + L] = True
                break
    return out
