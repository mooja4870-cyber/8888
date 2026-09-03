"""포트폴리오 단위 재검증 — 신호의 순수 엣지가 실전 제약 아래서도 살아남는가.

지금까지(screen/alpha/robust/cand2/holds)는 '건당 평균 bp'만 봤다. 그건 신호가 나올
때마다 무한히 진입할 수 있다고 가정한 숫자다. 실제로는:

  · 동시 보유가 MAX_POSITIONS로 막혀 좋은 신호를 놓친다 (슬롯 경쟁)
  · 손절이 걸려 보유기간을 다 채우지 못한다
  · 자금이 복리로 돌아 시점 순서가 결과를 바꾼다 (건당 평균에는 없는 효과)
  · 최고점 대비 낙폭이 실제 운용 가능성을 정한다

전략 (holds.py에서 확정된 국면별 최적 조합)
  BULL  Donchian-55            · 20일 보유
  BEAR  Donchian-55            ·  5일 보유
  RANGE Donchian-55 + 거래량필터 · 10일 보유

체결 규칙 (미래참조 없음)
  i봉 종가로 신호 → i+1봉 시가 진입 → (i+1+h)봉 시가 청산. 손절은 장중 고가/저가로 판정.
  국면은 직전 봉까지의 정보로만 판정(regime.classify).

비교 기준 두 가지 — 어느 쪽도 통과 못 하면 엣지가 아니다.
  ① 균등보유(베타)  : 같은 기간 10종목 동일 레버리지 바이앤홀드
  ② 무작위 진입(널) : 같은 날 · 같은 건수 · 같은 롱숏 비율로 종목만 무작위.
                      신호의 '종목·타이밍 선택'에만 값이 있는지 가린다.
"""
import numpy as np, pandas as pd
import regime as R
from screen import sig_donchian
import warnings; warnings.filterwarnings("ignore")

# ── 8402 실제 config.json 실측값 ──
MAX_POSITIONS   = 3
LEVERAGE        = 3
EQUITY_SCALE    = 0.5
MAX_NOTIONAL    = 5000.0
INIT_EQUITY     = 10000.0
COST_BP         = 10.0        # 왕복 전량 테이커 (비관)

HOLD_BY_REGIME  = {"BULL": 20, "BEAR": 5, "RANGE": 10}
VOLFILTER_REGIME = {"RANGE"}   # 이 국면에서만 거래량 확인을 요구한다
N_DONCHIAN      = 55


def build():
    """종목별 정렬된 배열 묶음을 만든다. 날짜는 전 종목 공통 인덱스로 맞춘다."""
    per = {}
    for sym in R.symbols():
        d = R.load(sym)
        reg = R.classify(d)
        sig = sig_donchian(d, N_DONCHIAN)
        volok = (d["volume"] > d["volume"].rolling(20).mean()).fillna(False)
        per[sym] = pd.DataFrame({
            "date": pd.to_datetime(d["date"]),
            "open": d["open"].values, "high": d["high"].values, "low": d["low"].values,
            "regime": reg.values, "sig": sig.values, "volok": volok.values,
        }).set_index("date")
    cal = sorted(set().union(*(p.index for p in per.values())))
    cal = pd.DatetimeIndex(cal)
    out = {}
    for sym, p in per.items():
        q = p.reindex(cal)
        # reindex가 만든 결측은 float nan이 된다 — 국면 없음을 None 하나로 통일해 둔다
        reg = np.array([r if isinstance(r, str) else None for r in q["regime"].values], dtype=object)
        out[sym] = dict(
            op=q["open"].values.astype(float), hi=q["high"].values.astype(float),
            lo=q["low"].values.astype(float), reg=reg,
            sig=np.nan_to_num(q["sig"].values.astype(float)).astype(int),
            volok=q["volok"].fillna(False).values.astype(bool),
            live=q["open"].notna().values,
        )
    return cal, out


def entries_for_day(D, syms, i):
    """i봉 종가 기준으로 확정된 진입 후보 — (sym, dir, hold). i+1봉 시가에 체결된다."""
    cand = []
    for s in syms:
        a = D[s]
        if not a["live"][i]:
            continue
        rg = a["reg"][i]
        if rg is None:
            continue
        sg = a["sig"][i]
        if sg == 0:
            continue
        if rg in VOLFILTER_REGIME and not a["volok"][i]:
            continue
        cand.append((s, int(sg), HOLD_BY_REGIME[rg], rg))
    return cand


def simulate(cal, D, stop_pct=None, mode="signal", rng=None, start=None, end=None,
             schedule=None):
    """mode
      signal      실제 Donchian 신호
      random      같은 날·같은 건수·같은 롱숏비율, 종목만 무작위  → '종목 선택'의 값
      schedule    같은 총건수·같은 롱숏비율, 날짜와 종목 모두 무작위 → '타이밍+종목'의 값
      regime_only 신호 없음. BULL이면 롱·BEAR면 숏만 매일 채운다 → '국면 방향'만의 값
    """
    syms = sorted(D)
    n = len(cal)
    i0 = 0 if start is None else int(np.searchsorted(cal, start))
    i1 = n if end is None else int(np.searchsorted(cal, end))

    equity = INIT_EQUITY
    open_pos = {}                      # sym -> dict
    curve, trades = [], []

    for i in range(i0, min(i1, n - 1)):
        # ── 1. 시가 청산 (보유기간 만료) ──
        for s in [s for s, p in open_pos.items() if p["exit_i"] == i]:
            p = open_pos.pop(s)
            px = D[s]["op"][i]
            if not np.isfinite(px):
                px = p["entry"]
            _close(p, px, "만료", equity_ref=None, trades=trades, cal=cal, i=i)
            equity += p["pnl"]

        # ── 2. 시가 진입 ──
        free = MAX_POSITIONS - len(open_pos)
        if free > 0 and equity > 0:
            if mode == "regime_only":
                cand = []
                for s in syms:
                    rg = D[s]["reg"][i - 1] if i > 0 else None
                    if rg in ("BULL", "BEAR"):
                        cand.append((s, 1 if rg == "BULL" else -1, HOLD_BY_REGIME[rg], rg))
            else:
                cand = entries_for_day(D, syms, i - 1) if i > 0 else []
            cand = [c for c in cand if c[0] not in open_pos and np.isfinite(D[c[0]]["op"][i])]
            if mode == "schedule":
                # 그날 배정된 건수·방향만 받고 종목은 무작위 — 날짜 자체가 뒤섞여 있다
                dirs = list(schedule.get(i, ()))
                pool = [s for s in syms if D[s]["live"][i] and s not in open_pos
                        and np.isfinite(D[s]["op"][i]) and D[s]["reg"][i - 1] is not None]
                k = min(len(dirs), len(pool))
                pick = rng.choice(len(pool), size=k, replace=False) if k else []
                cand = [(pool[j], dirs[t], HOLD_BY_REGIME[D[pool[j]]["reg"][i - 1]],
                         D[pool[j]]["reg"][i - 1]) for t, j in enumerate(pick)]
            elif mode == "random" and cand:
                # 같은 건수·같은 롱숏 비율, 종목만 그날 거래 가능한 것 중 무작위
                pool = [s for s in syms if D[s]["live"][i] and s not in open_pos
                        and np.isfinite(D[s]["op"][i]) and D[s]["reg"][i - 1] is not None]
                k = min(len(cand), len(pool))
                if k:
                    pick = rng.choice(len(pool), size=k, replace=False)
                    dirs = [c[1] for c in cand][:k]
                    rng.shuffle(dirs)
                    cand = [(pool[j], dirs[t],
                             HOLD_BY_REGIME[D[pool[j]]["reg"][i - 1]], D[pool[j]]["reg"][i - 1])
                            for t, j in enumerate(pick)]
                else:
                    cand = []
            # 슬롯 경쟁: 날짜별로 회전시켜 특정 종목이 구조적으로 유리해지지 않게 한다
            if len(cand) > free:
                cand = sorted(cand, key=lambda c: ((syms.index(c[0]) + i) % len(syms)))[:free]
            for s, sd, h, rg in cand:
                notional = min(equity * EQUITY_SCALE * LEVERAGE / MAX_POSITIONS, MAX_NOTIONAL)
                if notional <= 0:
                    continue
                px = D[s]["op"][i]
                open_pos[s] = dict(sym=s, dir=sd, entry=px, notional=notional,
                                   exit_i=min(i + h, n - 1), regime=rg, entry_i=i,
                                   stop=None if stop_pct is None else
                                   px * (1 - stop_pct * sd))

        # ── 3. 장중 손절 판정 ──
        if stop_pct is not None:
            for s in [s for s, p in open_pos.items() if p["stop"] is not None]:
                p = open_pos[s]
                hit = (D[s]["lo"][i] <= p["stop"]) if p["dir"] == 1 else (D[s]["hi"][i] >= p["stop"])
                if np.isfinite(D[s]["lo"][i]) and hit:
                    open_pos.pop(s)
                    _close(p, p["stop"], "손절", None, trades, cal, i)
                    equity += p["pnl"]

        curve.append((cal[i], equity + sum(_mtm(p, D, i) for p in open_pos.values())))
        if equity <= 0:
            break

    return pd.DataFrame(curve, columns=["date", "equity"]), pd.DataFrame(trades)


def _mtm(p, D, i):
    px = D[p["sym"]]["op"][i]
    if not np.isfinite(px):
        return 0.0
    return p["notional"] * (px / p["entry"] - 1) * p["dir"]


def _close(p, px, why, equity_ref, trades, cal, i):
    gross = p["notional"] * (px / p["entry"] - 1) * p["dir"]
    p["pnl"] = gross - p["notional"] * COST_BP / 10000.0
    trades.append(dict(sym=p["sym"], regime=p["regime"], dir=p["dir"], why=why,
                       entry_date=cal[p["entry_i"]], exit_date=cal[i],
                       bars=i - p["entry_i"], pnl=p["pnl"],
                       ret_bp=(px / p["entry"] - 1) * p["dir"] * 10000 - COST_BP))


def buyhold(cal, D, start=None, end=None):
    """균등보유 베타 기준선 — 같은 총노출(EQUITY_SCALE×LEVERAGE)로 10종목 동일비중."""
    syms = sorted(D)
    i0 = 0 if start is None else int(np.searchsorted(cal, start))
    i1 = len(cal) if end is None else int(np.searchsorted(cal, end))
    expo = EQUITY_SCALE * LEVERAGE
    rets = []
    for i in range(i0 + 1, min(i1, len(cal))):
        day = [D[s]["op"][i] / D[s]["op"][i - 1] - 1 for s in syms
               if np.isfinite(D[s]["op"][i]) and np.isfinite(D[s]["op"][i - 1]) and D[s]["op"][i - 1] > 0]
        rets.append(np.mean(day) * expo if day else 0.0)
    eq = INIT_EQUITY * np.cumprod(1 + np.array(rets))
    return pd.DataFrame({"date": cal[i0 + 1:i0 + 1 + len(eq)], "equity": eq})


def stats(curve):
    if curve.empty:
        return dict(ret=np.nan, cagr=np.nan, mdd=np.nan, sharpe=np.nan)
    e = curve["equity"].values
    yrs = (curve["date"].iloc[-1] - curve["date"].iloc[0]).days / 365.25
    ret = e[-1] / e[0] - 1
    cagr = (e[-1] / e[0]) ** (1 / yrs) - 1 if yrs > 0 and e[-1] > 0 else -1.0
    mdd = float(np.min(e / np.maximum.accumulate(e)) - 1)
    dr = np.diff(e) / e[:-1]
    sharpe = float(np.mean(dr) / np.std(dr) * np.sqrt(365)) if np.std(dr) > 0 else 0.0
    return dict(ret=ret, cagr=cagr, mdd=mdd, sharpe=sharpe)


def quarters(curve, k=4):
    """기간 k분할 수익률 — 국면 운을 엣지로 오인하지 않기 위한 검사."""
    if curve.empty:
        return []
    idx = np.linspace(0, len(curve) - 1, k + 1).astype(int)
    return [curve["equity"].iloc[idx[j + 1]] / curve["equity"].iloc[idx[j]] - 1 for j in range(k)]
