#!/usr/bin/env python3
"""verify_tf_8409.py — 8409를 1시간봉으로 바꿀지 검증

배경
────
8408·8409가 사실상 같은 봇으로 판명됐다(실측 2026-08-13).
  코드 동일 · 설정 132개 중 실제 차이 1개(USE_ADX_FILTER) ·
  매매 종목 9개 100% 일치 · **같은 종목·같은 방향·5분 이내 동시 진입 15/15건**
$30을 두 번 쓰면서 정보는 하나만 얻는 셈이다.

그래서 8409에 지금 가장 답을 알고 싶은 질문을 배정한다 — **타임프레임**.
실거래 관찰(2026-08-13): 같은 MFI 전략인데
  8401 1시간봉  7건  −0.6%
  8403 15분봉  26건  −7.2%
"자주 거래할수록 나빠진다"는 오늘 여러 검증에서 반복된 패턴이다. 다만 이는
OKX·MFI 한 쌍의 관찰이라, 거래소와 전략을 바꿔도 성립하는지 확인해야 한다.

성립하면 2×2 대조가 완성된다.
              15분봉   1시간봉
  OKX·MFI      8403     8401
  BNC·이중BB   8408    **8409**

방법
────
8408 전략(이중볼린저)을 15분봉/1시간봉 두 데이터에 각각 돌려, 국면이 정반대인
두 구간에서 비교한다. 청산 경로는 현행 실거래 설정과 동일하게 맞춘다
(분할익절·본전보호·횡보청산·긴급트레일 전부 해제, 방향 게이트 ON).
보유 한도는 '24봉'으로 등가 환산한다(15m=6시간, 1h=24시간).
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = "/Users/l/project/8408"
FEE = 0.001
MAX_POS = 3
WARMUP = 800
sys.path.insert(0, BOT)
os.chdir(BOT)


def load(tf):
    """tf='15m'이면 lab_cache_180, '1h'이면 lab_cache_tf에서 읽는다."""
    if tf == "15m":
        pat, cut = "/Users/l/project/8888/lab_cache_180/binance_15m_*.json", "15m_"
    else:
        pat, cut = "/Users/l/project/8888/lab_cache_tf/1h_*.json", "1h_"
    out = {}
    for p in sorted(glob.glob(pat)):
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        c, h, l = df["close"], df["high"], df["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=14, adjust=False).mean()
        out[os.path.basename(p).split(cut)[1].split("_USDT")[0]] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def get_signals(frames, tf):
    cache = f"/Users/l/project/8888/lab/_sigcache_8408_{tf}.json"
    if os.path.exists(cache):
        d = json.load(open(cache))
        if set(d) == set(frames):
            print(f"    [{tf}] 신호 캐시 재사용", flush=True)
            return d
    from core.strategy import StrategyEngine
    st = StrategyEngine()
    out = {}
    for s, df in frames.items():
        sg = []
        for i in range(WARMUP, len(df) - 1):
            g = st.generate_signal(df.iloc[i - WARMUP:i], s)
            if g.direction == "none":
                continue
            e, sl, tp = g.close, g.swing_sl_price, g.tp1_price
            if not (e > 0 and sl > 0 and tp > 0):
                continue
            risk = abs(e - sl) / e
            if risk <= 0:
                continue
            sg.append({"i": i, "dir": g.direction, "e": e, "risk": risk,
                       "rr": abs(tp - e) / e / risk})
        out[s] = sg
        print(f"    [{tf}] {s:<9} 신호 {len(sg)}건", flush=True)
    json.dump(out, open(cache, "w"))
    return out


def run_trade(df, s, direction, hold_bars, k_ch=3.0):
    """현행 실거래 청산 경로: 손절 + 거래소 TP + 샹들리에 트레일링 + 보유한도."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = direction == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak = e
    end = min(n - 1, i + hold_bars)
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
        peak = max(peak, hi) if long else min(peak, lo)
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k_ch * a) if long else (peak + k_ch * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if not done:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), out - FEE


def simulate(frames, sigs, gates, lo, hi, hold_bars):
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
        ei, p = run_trade(frames[sym], s, d, hold_bars)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
    return pnl


def main():
    ema = lambda a, sp: pd.Series(a).ewm(span=sp, adjust=False).mean().values
    print("  " + "═" * 76)
    print(f"  {'타임프레임':<24}{'봉인 앞절반(하락)':>25}{'개발 뒤절반(상승)':>25}")
    print("  " + "─" * 76)
    res = {}
    # 게이트는 '12시간'으로 등가 환산: 15분봉 48봉 / 1시간봉 12봉
    for tf, gate_span, hold in (("15m", 48, 24), ("1h", 12, 24)):
        frames = load(tf)
        n0 = len(next(iter(frames.values()))); mid = n0 // 2
        sigs = get_signals(frames, tf)
        gates = {s: np.where(d["close"].values > ema(d["close"].values, gate_span), 1, -1)
                 for s, d in frames.items()}
        cells, nets = [], []
        for a, b in ((0, mid), (mid, n0)):
            p = simulate(frames, sigs, gates, a, b, hold)
            net = sum(p) * 100
            nets.append(net)
            wr = 100 * sum(1 for x in p if x > 0) / len(p) if p else 0
            cells.append(f"{len(p)}건 {wr:.0f}% {net:+.1f}%")
        res[tf] = nets
        days = n0 * (15 if tf == "15m" else 60) / 60 / 24
        print(f"  {tf + f' (총 {days:.0f}일)':<24}{cells[0]:>25}{cells[1]:>25}")
    print("  " + "─" * 76)
    d0 = res["1h"][0] - res["15m"][0]
    d1 = res["1h"][1] - res["15m"][1]
    print(f"  1시간봉 − 15분봉: 봉인 {d0:+.1f}%p · 개발 {d1:+.1f}%p")
    if d0 > 0 and d1 > 0:
        print("  → 두 구간 모두 1시간봉 우세. **8409를 1시간봉으로 바꾸는 것이 옳다.**")
    elif d0 < 0 and d1 < 0:
        print("  → 두 구간 모두 15분봉 우세. 바꾸지 말 것.")
    else:
        print("  → 엇갈림 = 국면 의존. 근거 없음(다른 변수를 찾아야 함).")


if __name__ == "__main__":
    main()
