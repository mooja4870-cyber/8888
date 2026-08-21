#!/usr/bin/env python3
"""verify_ma_expanded.py — 이동평균 20/100을 확대 종목군으로 최종확인

경위
────
문헌 지지 전략 5종 × 부가전략 4종 × 손절 2 × 보유 2 = 80조합을 88종목 3년으로 돌렸다.
가장 강한 것이 **이동평균 20/100 · 손절 ATR3.0 · 보유 20일**이었다.
  탐색 구간(915일): 103건 승58% 건당 +10.95±3.77(2.9σ) · 월 +5.2% · 최대낙폭 −12.1%
그런데 **최종확인 구간(최근 180일)이 22건뿐**이라 판정이 안 됐다(월 −0.0%).

그래서 종목을 88 → **194개**로 늘렸다(중앙값 952일). 최종확인 표본이 4~5배가 된다.

이번 자료의 특성 — 두 가지를 반드시 처리한다
──────────────────────────────────────────
1. **종목마다 이력 길이가 다르다.** 가장 짧은 종목에 맞춰 자르면(이전 코드) 자료를
   대부분 버린다. 그래서 **날짜(타임스탬프) 기준 공통 축**에 맞춘다.
2. **상장 직후 급등락**은 재현 불가능한 수익을 만든다. **상장 후 첫 60일은 제외**한다.
"""
import glob, json, os, sys
import numpy as np, pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_4h_all"
FEE, SLIP, MAX_POS = 0.001, 0.0002, 3
SKIP_AFTER_LIST = 60      # 상장 후 제외 일수
HOLDOUT_DAYS = 180
DAY_MS = 86400 * 1000


def load_daily_aligned():
    """4시간봉 6개=1일로 합치고, **날짜 기준 공통 축**에 정렬한다.

    반환 (frames, n_days). frames[sym]은 공통 축 길이의 DataFrame이며
    자료가 없는 날은 NaN이다(전략·청산이 NaN을 건너뛴다).
    """
    raw = {}
    for p in sorted(glob.glob(f"{CACHE}/okx_4h_*.json")):
        s = os.path.basename(p).replace("okx_4h_", "").replace(".json", "")
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        df["day"] = (df["ts"] // DAY_MS).astype("int64")
        g = df.groupby("day")
        d = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                          "low": g["low"].min(), "close": g["close"].last(),
                          "volume": g["volume"].sum()})
        raw[s] = d
    days = sorted(set().union(*[set(d.index) for d in raw.values()]))
    idx = pd.Index(days, name="day")
    frames = {}
    for s, d in raw.items():
        d = d.reindex(idx)
        c, h, l = d["close"], d["high"], d["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        d["_atr"] = tr.ewm(span=14, adjust=False).mean()
        d["_vol"] = c.pct_change().rolling(20).std()
        # 상장 후 첫 SKIP_AFTER_LIST일 차단
        valid = np.where(c.notna().values)[0]
        d["_ok"] = False
        if len(valid):
            d.iloc[valid[0] + SKIP_AFTER_LIST:, d.columns.get_loc("_ok")] = True
        frames[s] = d.reset_index(drop=True)
    return frames, len(idx)


def ma_cross(df, fast, slow):
    c = df["close"]
    f, s = c.rolling(fast).mean().values, c.rolling(slow).mean().values
    okv = df["_ok"].values
    out = []
    for t in range(slow + 1, len(c) - 1):
        if not okv[t] or not (np.isfinite(f[t]) and np.isfinite(s[t]) and np.isfinite(f[t - 1])):
            continue
        if f[t - 1] <= s[t - 1] and f[t] > s[t]:
            out.append((t, "long"))
        elif f[t - 1] >= s[t - 1] and f[t] < s[t]:
            out.append((t, "short"))
    return out


def run_trade(df, t, direction, sl_atr, hold):
    o, h, l, c = (df["open"].values, df["high"].values,
                  df["low"].values, df["close"].values)
    atr = df["_atr"].values
    n = len(c)
    i = t + 1
    if i >= n or not np.isfinite(o[i]):
        return i, None
    long = direction == "long"
    e = o[i] * (1 + SLIP) if long else o[i] * (1 - SLIP)
    a0 = atr[t]
    if not np.isfinite(a0) or a0 <= 0 or e <= 0:
        return i, None
    risk = sl_atr * a0 / e
    if risk <= 0 or risk > 0.30:
        return i, None
    sl = e * (1 - risk) if long else e * (1 + risk)
    end, j, out = min(n - 1, i + hold), i, None
    while j <= end:
        if np.isfinite(l[j]) and np.isfinite(h[j]):
            if (long and l[j] <= sl) or (not long and h[j] >= sl):
                out = (sl - e) / e if long else (e - sl) / e
                break
        j += 1
    if out is None:
        k = min(j, end)
        while k > i and not np.isfinite(c[k]):
            k -= 1
        if not np.isfinite(c[k]):
            return i, None
        out = (c[k] - e) / e if long else (e - c[k]) / e
    return min(j, end), out - FEE - SLIP


def trades(frames, sigmap, lo, hi, sl_atr, hold):
    allsig = sorted(((t, s, d) for s, v in sigmap.items() for t, d in v
                     if lo <= t < hi), key=lambda x: x[0])
    busy, openp, out = {}, [], []
    for t, sym, d in allsig:
        openp = [x for x in openp if x > t]
        if busy.get(sym, -1) >= t or len(openp) >= MAX_POS:
            continue
        ei, p = run_trade(frames[sym], t, d, sl_atr, hold)
        if p is None:
            continue
        out.append((t, ei, p))
        busy[sym] = ei
        openp.append(ei)
    return out


def stat(tr):
    if len(tr) < 20:
        return None
    a = np.array([p for _, _, p in tr]) * 100
    return {"n": len(a), "mean": a.mean(), "win": 100 * (a > 0).mean(),
            "se": a.std(ddof=1) / np.sqrt(len(a)),
            "sigma": a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))}


def acct(tr, days, alloc=0.15):
    if not tr:
        return None
    bal = peak = 1.0
    mdd = 0.0
    for ei, p in sorted([(x[1], x[2]) for x in tr]):
        bal *= (1 + p * alloc)
        peak = max(peak, bal)
        mdd = min(mdd, bal / peak - 1)
    mret = (bal ** (30 / days) - 1) * 100 if days > 0 and bal > 0 else float("nan")
    return {"bal": bal, "mdd": mdd * 100, "mret": mret}


def line(nm, tr, days, alloc=0.15):
    s, a = stat(tr), acct(tr, days, alloc)
    if not tr:
        return f"  {nm:<22} 거래없음"
    st = (f"{s['mean']:+.2f}±{s['se']:.2f}({s['sigma']:+.1f}σ)" if s
          else f"{len(tr)}건 표본부족")
    return (f"  {nm:<22}{len(tr):>5}{s['win'] if s else 0:>5.0f}%{st:>20}"
            f"{a['bal']:>8.2f}{a['mdd']:>8.1f}%{a['mret']:>7.1f}%")


def main():
    frames, N = load_daily_aligned()
    SE = N - HOLDOUT_DAYS
    print(f"  {len(frames)}종목 · 공통 축 {N}일 · 상장 후 {SKIP_AFTER_LIST}일 제외")
    print(f"  탐색 0~{SE}일 · **최종확인 {SE}~{N}일({HOLDOUT_DAYS}일)**")

    for fast, slow in ((20, 100), (10, 40)):
        sm = {s: ma_cross(d, fast, slow) for s, d in frames.items()}
        tot = sum(len(v) for v in sm.values())
        print(f"\n  ■ 이동평균 {fast}/{slow} · 손절 ATR3.0 · 보유 20일 · 노출 15% "
              f"(신호 {tot}건)")
        print(f"  {'구간':<22}{'건수':>5}{'승률':>6}{'건당':>20}{'계좌':>8}{'낙폭':>8}{'월수익':>7}")
        print("  " + "─" * 76)
        q = SE // 3
        segs = [(f"탐색 1/3", 0, q), (f"탐색 2/3", q, 2 * q), (f"탐색 3/3", 2 * q, SE),
                ("탐색 전체", 0, SE), ("★최종확인", SE, N)]
        for nm, lo, hi in segs:
            print(line(nm, trades(frames, sm, lo, hi, 3.0, 20), hi - lo))
        print("  " + "─" * 76)

    # 채택 후보의 노출 비중별 위험/수익
    sm = {s: ma_cross(d, 20, 100) for s, d in frames.items()}
    tr_all = trades(frames, sm, 0, N, 3.0, 20)
    tr_ho = trades(frames, sm, SE, N, 3.0, 20)
    print(f"\n  ■ 이동평균 20/100 노출 비중별 (전 기간 {N}일 / 최종확인 {HOLDOUT_DAYS}일)")
    print(f"  {'비중':>6}{'전기간 월수익':>14}{'전기간 낙폭':>12}"
          f"{'최종확인 월수익':>16}{'최종확인 낙폭':>14}")
    for al in (0.05, 0.10, 0.15, 0.30):
        a, b = acct(tr_all, N, al), acct(tr_ho, HOLDOUT_DAYS, al)
        print(f"  {al*100:>5.0f}%{a['mret']:>13.1f}%{a['mdd']:>11.1f}%"
              f"{b['mret']:>15.1f}%{b['mdd']:>13.1f}%")


if __name__ == "__main__":
    main()
