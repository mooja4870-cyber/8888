#!/usr/bin/env python3
"""strategy_sweep.py — 전략 4종 × 타임프레임 × 손절/익절 전수 검색

왜 이렇게 하는가
───────────────
"4개 봇에 4개 전략을 걸고 잘되는 걸 고르자"는 방향은 옳다. 그런데 **실거래로 고르면**
안 된다. 계산해 보면 엣지가 0인 전략 4개를 30일 돌려도 '최고 봇'은 평균 +20%를
찍고, 플러스일 확률이 94%다. 그 우승자는 실력이 아니라 운이고 다음 달에 무너진다.
**이게 100개 봇을 만든 방법이다.**

그래서 고르는 곳만 바꾼다. 전략당 표본이 300건(실거래 30일)이 아니라 수천 건
(180일 × 61종목)이고, 조합을 수백 개 돌려도 돈이 안 든다.

진입가 규칙 — 오늘 찾은 결함을 되풀이하지 않는다
────────────────────────────────────────────
신호는 **닫힌 봉 t까지**만 보고 만들고, 진입은 **봉 t+1의 시가**로 한다.
봇이 실제로 하는 일과 같다(봉이 닫히면 스캔이 돌고 시장가로 들어간다).
기존 백테스트는 신호봉보다 한 봉 **앞선** 종가에 샀고, 그래서 +30%가 나왔다.
고쳐서 재보니 −0.148%였고 실거래 실측 −0.147%와 일치했다.

전략 4종
  1 볼린저회귀   역추세 — 밴드 밖으로 나가면 되돌림에 건다 (기존 계열, 대조군)
  2 이중볼린저   역추세 — 2σ 밖으로 나갔다가 1σ 안으로 복귀할 때 (8408·8409 계열)
  3 돈치안돌파   추세  — N봉 최고가 돌파 시 추종 (신규)
  4 횡단면모멘텀 추세  — 종목을 수익률로 줄 세워 상위 매수·하위 매도 (신규)

3·4는 **진입이 늦어도 살아남는지**를 보려고 넣었다. 역추세는 신호 직후 몇 분에
엣지가 몰려 있어 지연에 죽는다. 추세는 몇 시간~며칠 이어지므로 버틸 수 있다.

채택 기준: 앞 90일(봉인)과 뒤 90일(개발) **양쪽에서** 건당 손익이 플러스.
"""
import glob, json, os, sys
import numpy as np, pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_live"
FEE, SLIP, MAX_POS = 0.001, 0.0002, 3
WARM = 250


# ── 데이터 ────────────────────────────────────────────────────────────────
def load(tf):
    """tf: '15m' | '1h' | '4h'. 15분봉 원자료를 합쳐 만든다."""
    mult = {"15m": 1, "1h": 4, "4h": 16}[tf]
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/okx_15m_*.json")):
        s = os.path.basename(p).replace("okx_15m_", "").replace(".json", "")
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        if mult > 1:
            n = len(df) // mult * mult
            df = df.iloc[len(df) - n:].reset_index(drop=True)
            g = df.groupby(df.index // mult)
            df = pd.DataFrame({"ts": g["ts"].first(), "open": g["open"].first(),
                               "high": g["high"].max(), "low": g["low"].min(),
                               "close": g["close"].last(), "volume": g["volume"].sum()
                               }).reset_index(drop=True)
        c, h, l = df["close"], df["high"], df["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=14, adjust=False).mean()
        out[s] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


# ── 전략: 닫힌 봉 t까지만 보고 (t, 방향) 목록을 낸다 ──────────────────────
def sig_bb_revert(df, period=20, std=2.0):
    c = df["close"]
    m = c.rolling(period).mean()
    s = c.rolling(period).std()
    up, dn = m + std * s, m - std * s
    out = []
    cv, uv, dv = c.values, up.values, dn.values
    for t in range(WARM, len(cv) - 1):
        if not np.isfinite(uv[t]):
            continue
        if cv[t] < dv[t]:
            out.append((t, "long"))
        elif cv[t] > uv[t]:
            out.append((t, "short"))
    return out


def sig_double_bb(df, period=20, s_out=2.0, s_in=1.0):
    """2σ 밖으로 나갔다가 1σ 안으로 복귀하는 순간."""
    c = df["close"]
    m = c.rolling(period).mean()
    sd = c.rolling(period).std()
    cv, mv, sv = c.values, m.values, sd.values
    out, armed = [], 0
    for t in range(WARM, len(cv) - 1):
        if not np.isfinite(sv[t]):
            continue
        up_o, dn_o = mv[t] + s_out * sv[t], mv[t] - s_out * sv[t]
        up_i, dn_i = mv[t] + s_in * sv[t], mv[t] - s_in * sv[t]
        if cv[t] < dn_o:
            armed = -1
        elif cv[t] > up_o:
            armed = +1
        elif armed == -1 and cv[t] > dn_i:
            out.append((t, "long"))
            armed = 0
        elif armed == +1 and cv[t] < up_i:
            out.append((t, "short"))
            armed = 0
    return out


def sig_donchian(df, n=48):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    hh = pd.Series(h).rolling(n).max().shift(1).values
    ll = pd.Series(l).rolling(n).min().shift(1).values
    out = []
    for t in range(WARM, len(c) - 1):
        if not np.isfinite(hh[t]):
            continue
        if c[t] > hh[t]:
            out.append((t, "long"))
        elif c[t] < ll[t]:
            out.append((t, "short"))
    return out


def sig_xmom(frames, look=96, rebal=24, top=6):
    """횡단면 모멘텀 — 종목별이 아니라 전 종목을 함께 줄 세운다."""
    syms = list(frames)
    n = len(next(iter(frames.values())))
    closes = np.array([frames[s]["close"].values for s in syms])
    out = {s: [] for s in syms}
    for t in range(max(WARM, look), n - 1, rebal):
        r = (closes[:, t] - closes[:, t - look]) / closes[:, t - look]
        order = np.argsort(r)
        for k in order[-top:]:
            out[syms[k]].append((t, "long"))
        for k in order[:top]:
            out[syms[k]].append((t, "short"))
    return out


# ── 청산 엔진 (전략 공용) ────────────────────────────────────────────────
def run_trade(df, t, direction, sl_mult, rr, k_ch, hold):
    """진입 = 봉 t+1 시가. 손절 = ATR×sl_mult. 익절 = 손절×rr. 샹들리에 추적."""
    o, h, l, c = (df["open"].values, df["high"].values,
                  df["low"].values, df["close"].values)
    atr = df["_atr"].values
    n = len(c)
    i = t + 1
    if i >= n:
        return i, None
    long = direction == "long"
    e = o[i] * (1 + SLIP) if long else o[i] * (1 - SLIP)
    a0 = atr[t]
    if not np.isfinite(a0) or a0 <= 0 or e <= 0:
        return i, None
    risk = sl_mult * a0 / e
    if risk <= 0 or risk > 0.20:
        return i, None
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak, end, j = e, min(n - 1, i + hold), i
    out = None
    while j <= end:
        gain = (h[j] - e) / e if long else (e - l[j]) / e
        if (long and l[j] <= sl) or (not long and h[j] >= sl):
            out = (sl - e) / e if long else (e - sl) / e
            break
        if gain >= tp_pct:
            out = tp_pct
            break
        peak = max(peak, h[j]) if long else min(peak, l[j])
        a = atr[j] if np.isfinite(atr[j]) else 0.0
        ch = (peak - k_ch * a) if long else (peak + k_ch * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if out is None:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), out - FEE - SLIP


def simulate(frames, sigmap, lo, hi, sl_mult, rr, k_ch, hold):
    allsig = sorted(((t, s, d) for s, v in sigmap.items() for t, d in v
                     if lo <= t < hi), key=lambda x: x[0])
    busy, openp, pnl = {}, [], []
    for t, sym, d in allsig:
        openp = [x for x in openp if x > t]
        if busy.get(sym, -1) >= t or len(openp) >= MAX_POS:
            continue
        ei, p = run_trade(frames[sym], t, d, sl_mult, rr, k_ch, hold)
        if p is None:
            continue
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def stat(p):
    if len(p) < 30:
        return None
    a = np.array(p) * 100
    return {"n": len(a), "sum": a.sum(), "mean": a.mean(),
            "se": a.std(ddof=1) / np.sqrt(len(a)), "win": 100 * (a > 0).mean()}


def fmt(s):
    if s is None:
        return "표본부족"
    return f"{s['n']:>4}건 승{s['win']:>2.0f}% {s['sum']:+7.1f}% (건당 {s['mean']:+.3f}±{s['se']:.3f})"


def main():
    TFS = ["15m", "1h", "4h"]
    results = []
    for tf in TFS:
        frames = load(tf)
        n0 = len(next(iter(frames.values())))
        mid = n0 // 2
        bars_per_day = {"15m": 96, "1h": 24, "4h": 6}[tf]
        print(f"\n{'═'*100}\n  ■ {tf} — {len(frames)}종목 · {n0}봉 = {n0/bars_per_day:.0f}일", flush=True)

        strat = {
            "볼린저회귀": {s: sig_bb_revert(d) for s, d in frames.items()},
            "이중볼린저": {s: sig_double_bb(d) for s, d in frames.items()},
            "돈치안돌파": {s: sig_donchian(d, n=max(12, bars_per_day // 2)) for s, d in frames.items()},
            "횡단면모멘텀": sig_xmom(frames, look=bars_per_day, rebal=max(4, bars_per_day // 4)),
        }
        hold = bars_per_day // 2 if tf != "4h" else 12
        print(f"  {'전략':<14}{'손절ATR':>8}{'RR':>5}{'K':>5}{'봉인 앞90일':>32}{'개발 뒤90일':>32}", flush=True)
        print("  " + "─" * 98, flush=True)
        for name, sm in strat.items():
            tot = sum(len(v) for v in sm.values())
            if tot < 60:
                print(f"  {name:<14} 신호 {tot}건 — 부족", flush=True)
                continue
            for sl_mult in (1.0, 2.0):
                for rr in (1.5, 3.0):
                    a = stat(simulate(frames, sm, 0, mid, sl_mult, rr, 4.0, hold))
                    b = stat(simulate(frames, sm, mid, n0, sl_mult, rr, 4.0, hold))
                    ok = (a and b and a["mean"] > 0 and b["mean"] > 0)
                    mark = "  ★양쪽 플러스" if ok else ""
                    print(f"  {name:<14}{sl_mult:>8.1f}{rr:>5.1f}{4.0:>5.1f}"
                          f"{fmt(a):>32}{fmt(b):>32}{mark}", flush=True)
                    if ok:
                        results.append((tf, name, sl_mult, rr, a, b))

    print(f"\n{'═'*100}\n  ■ 양쪽 구간 플러스로 살아남은 조합", flush=True)
    if not results:
        print("    없음 — 전부 기각", flush=True)
    else:
        for tf, name, sm, rr, a, b in sorted(results, key=lambda x: -(x[4]["mean"] + x[5]["mean"])):
            print(f"    {tf:<4} {name:<14} 손절ATR{sm:.1f} RR{rr:.1f}  "
                  f"봉인 {a['mean']:+.3f}±{a['se']:.3f} / 개발 {b['mean']:+.3f}±{b['se']:.3f}", flush=True)


if __name__ == "__main__":
    main()
