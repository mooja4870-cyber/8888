#!/usr/bin/env python3
"""verify_dynamic_exit.py — 동적청산(USE_DYNAMIC_SLTP) 검증

동작 (core/trailing_stop_manager.py _check_dynamic_exit)
──────────────────────────────────────────────────────
수익률 1.8% 미만인 포지션만 대상으로, 15분봉 지표에서 '둔화 신호'를 센다.
  · ADX 하락 · 거래량 급감 · 변동성 축소 · 단기이평 역전 · RSI 과매수/과매도 이탈
신호 수에 따라 Step 1~3으로 올리고 **샹들리에 K와 콜백을 단계적으로 좁힌다**.
수익률 0.2% 이하면 EMA 데드크로스로 '진입근거 무효화' 판정까지 한다.

즉 **"약해 보이면 더 빨리 자른다"** 이고, 이번 주 다섯 번 확인한
'조기 청산하지 마라'와 정면으로 반대되는 장치다. 그래서 검증한다.

재현
────
실거래 로직을 그대로 옮기면 지표 5종을 매 봉 계산해야 해 느리고, 옮기는 과정에서
오차가 생긴다. 대신 **효과의 방향만** 재현한다 —
"수익 1.8% 미만 구간에서 둔화 신호가 잡히면 K를 축소" 를 모델링하고,
둔화 판정은 실거래와 같은 지표(ADX·EMA9/21·거래량·RSI)로 한다.

두 구간(봉인=하락, 개발=상승) 모두 개선되는 쪽만 채택한다.
"""
import json, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/l/project/8888")
exec(open("/Users/l/project/8888/lab/verify_gate_design.py").read()
     .split("def main():")[0].replace('if __name__', '#'))

FEE = 0.001
MAX_POS = 3
DYN_TRIGGER = 0.018        # 이 수익률 미만에서만 동적청산이 작동
K_BASE = 4.0               # 15분봉 채택값


def add_indicators(df):
    """둔화 판정용 지표. 실거래와 같은 종류를 쓴다."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    df["ema9"] = c.ewm(span=9, adjust=False).mean()
    df["ema21"] = c.ewm(span=21, adjust=False).mean()
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()
    up, dn = h.diff(), -l.diff()
    plus = 100 * (up.where((up > dn) & (up > 0), 0.0)).ewm(span=14, adjust=False).mean() / atr
    minus = 100 * (dn.where((dn > up) & (dn > 0), 0.0)).ewm(span=14, adjust=False).mean() / atr
    dx = 100 * (plus - minus).abs() / (plus + minus).replace(0, np.nan)
    df["adx"] = dx.ewm(span=14, adjust=False).mean()
    d = c.diff()
    g = d.clip(lower=0).ewm(span=14, adjust=False).mean()
    ls = (-d.clip(upper=0)).ewm(span=14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + g / ls.replace(0, np.nan))
    df["vol_sma"] = v.rolling(20).mean()
    df["std"] = c.rolling(20).std()
    return df


def weakness(df, j, long):
    """둔화 신호 개수. 실거래 _check_dynamic_exit의 판정과 같은 항목."""
    if j < 2:
        return 0
    cur, prv = df.iloc[j], df.iloc[j - 1]
    n = 0
    if cur["adx"] == cur["adx"] and prv["adx"] == prv["adx"] and cur["adx"] < prv["adx"]:
        n += 1
    if cur["vol_sma"] == cur["vol_sma"] and cur["volume"] < cur["vol_sma"] * 0.7:
        n += 1
    if cur["std"] == cur["std"] and prv["std"] == prv["std"] and cur["std"] < prv["std"] * 0.8:
        n += 1
    if long and cur["ema9"] < prv["ema9"]:
        n += 1
    if (not long) and cur["ema9"] > prv["ema9"]:
        n += 1
    if long and cur["rsi"] == cur["rsi"] and prv["rsi"] >= 70 > cur["rsi"]:
        n += 1
    if (not long) and cur["rsi"] == cur["rsi"] and prv["rsi"] <= 30 < cur["rsi"]:
        n += 1
    return n


def run_trade(df, s, direction, cfg, dynamic):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    hold = int(g("MAX_HOLDING_HOURS", 6.0) * 4) or 10 ** 9
    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = direction == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak = e
    end = min(n - 1, i + hold)
    j, done, out = i, False, 0.0
    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e) / e if long else (e - lo) / e
        if (long and lo <= sl) or (not long and hi >= sl):
            out = (sl - e) / e if long else (e - sl) / e
            done = True
            break
        if gain >= tp_pct:
            out = tp_pct
            done = True
            break
        k_cur = K_BASE
        if dynamic and gain < DYN_TRIGGER:
            w = weakness(df, j, long)
            if w >= 4:
                k_cur = K_BASE * 0.25       # Step 3
            elif w == 3:
                k_cur = K_BASE * 0.5        # Step 2
            elif w == 2:
                k_cur = K_BASE * 0.75       # Step 1
        peak = max(peak, hi) if long else min(peak, lo)
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k_cur * a) if long else (peak + k_cur * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if not done:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), out - FEE


def simulate(frames, sigs, gates, cfg, lo, hi, dynamic):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        d = s["dir"]
        if (gates[sym][i - 1] > 0) != (d == "long"):
            continue
        ei, p = run_trade(frames[sym], s, d, cfg, dynamic)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
    return pnl


def main():
    frames = {k: add_indicators(v) for k, v in load().items()}
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    sigs = get_signals(frames)
    cfg = dict(json.load(open(f"{BOT}/config.json")))
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 48), 1, -1)
             for s, d in frames.items()}
    print("  " + "═" * 72)
    print(f"  {'설정':<26}{'봉인 앞90일(하락)':>22}{'개발 뒤90일(상승)':>22}")
    print("  " + "─" * 72)
    res = {}
    for nm, dyn in (("동적청산 ON (현행)", True), ("동적청산 OFF", False)):
        cells, nets = [], []
        for a, b in ((0, mid), (mid, n0)):
            p = simulate(frames, sigs, gates, cfg, a, b, dyn)
            net = sum(p) * 100
            nets.append(net)
            wr = 100 * sum(1 for x in p if x > 0) / len(p) if p else 0
            cells.append(f"{len(p)}건 {wr:.0f}% {net:+.1f}%")
        res[nm] = nets
        print(f"  {nm:<26}{cells[0]:>22}{cells[1]:>22}")
    print("  " + "─" * 72)
    on, off = res["동적청산 ON (현행)"], res["동적청산 OFF"]
    print(f"  OFF − ON: 봉인 {off[0]-on[0]:+.1f}%p · 개발 {off[1]-on[1]:+.1f}%p")
    if off[0] > on[0] and off[1] > on[1]:
        print("  → 두 구간 모두 OFF 우세. **동적청산을 끄는 것이 옳다.**")
    elif off[0] < on[0] and off[1] < on[1]:
        print("  → 두 구간 모두 ON 우세. 유지할 것.")
    else:
        print("  → 엇갈림 = 국면 의존. 판정 보류.")


if __name__ == "__main__":
    main()
