#!/usr/bin/env python3
"""verify_exits_live_universe.py — 조기청산 장치 5종을 '실거래 종목군'에서 재검증

왜 다시 하는가
─────────────
조기청산 6종 제거는 모두 거래대금 상위 **15종목**에서 검증했다. 그런데 실거래는
61종목(≥$50만·상위 80)에서 이뤄졌고 겹치는 건 6개(13%)뿐이다. 8403 거래의 80%가
$3M 미만 종목이었고 손실의 86%가 거기서 났다. 즉 **대형주로 검증하고 소형주로
매매했다.** 종목군이 바뀌어도 같은 결론이 나오는지 확인해야 그 원리를 믿을 수 있다.

검증 대상 (config.json 실제 파라미터를 그대로 씀)
  1 본전보호  BE_GUARD_TRIGGER 1.2% 도달 시 SL을 진입가+0.1%로
  2 횡보청산  45분(15분봉 3봉) 뒤 손실 0.5% 이내면 청산, 수익 중이면 유예
  3 분할익절  min(1.5%, TP×0.5)에서 절반 청산 + 잔량 본전스톱
  4 긴급TS    TP의 85% 도달 시 샹들리에 K를 4.0 → 0.8로 축소
  5 샹들리에  K 격자
동적청산(USE_DYNAMIC_SLTP)은 RSI 재계산이 필요해 제외한다 — K 격자가 대리한다.

기준: 봉인(앞 90일·하락 국면)과 개발(뒤 90일·상승 국면) **양쪽에서** 개선돼야 채택.
"""
import glob, json, os, sys
import numpy as np, pandas as pd

BOT = "/Users/l/project/8403"
CACHE = "/Users/l/project/8888/lab_cache_live"
SIGCACHE = "/Users/l/project/8888/lab/_sigcache_8403_live61.json"
FEE = 0.001
MAX_POS = 3
HOLD = 24            # MAX_HOLDING_HOURS 6h ÷ 15m = 24봉
GATE_EMA = 48

# 8403 config.json 실제값
BE_TRIGGER, BE_PROTECT = 0.012, 0.001
TIMEOUT_BARS, TIMEOUT_MAX_LOSS = 3, 0.005      # 45분 ÷ 15분
PARTIAL_TRIGGER, PARTIAL_FRAC = 0.015, 0.5
SCALEOUT_RATIO = 0.5
EMERG_RATIO, EMERG_K = 0.85, 0.8

sys.path.insert(0, BOT)


def load():
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/okx_15m_*.json")):
        s = os.path.basename(p).replace("okx_15m_", "").replace(".json", "")
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        c, h, l = df["close"], df["high"], df["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        df["_atr"] = tr.ewm(span=14, adjust=False).mean()
        out[s] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def run_trade(df, s, k_ch, be=False, timeout=False, partial=False,
              scaleout=False, emerg=False):
    """한 거래를 봉 단위로 굴린다. 반환 (청산봉, 수익률).

    봉 안에서 고가·저가 순서를 알 수 없으므로 손절을 먼저 본다(보수적).
    이 규칙은 모든 설정에 동일하게 적용되므로 비교에는 영향이 없다.
    """
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = s["dir"] == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak = e
    end = min(n - 1, i + HOLD)

    part_trig = min(PARTIAL_TRIGGER, tp_pct * SCALEOUT_RATIO) if scaleout else PARTIAL_TRIGGER
    booked = 0.0          # 분할익절로 이미 확정한 수익
    remain = 1.0          # 남은 비중
    j, done, out = i, False, 0.0

    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e) / e if long else (e - lo) / e

        if (long and lo <= sl) or (not long and hi >= sl):
            out = (sl - e) / e if long else (e - sl) / e
            out *= remain
            done = True
            break
        if gain >= tp_pct:
            out = tp_pct * remain
            done = True
            break

        # 분할익절 — 절반 확정하고 잔량은 본전에 묶인다
        if partial and remain == 1.0 and gain >= part_trig:
            booked += part_trig * PARTIAL_FRAC
            remain = 1.0 - PARTIAL_FRAC
            b = e * (1 + BE_PROTECT) if long else e * (1 - BE_PROTECT)
            sl = max(sl, b) if long else min(sl, b)
        # 본전보호
        if be and gain >= BE_TRIGGER:
            b = e * (1 + BE_PROTECT) if long else e * (1 - BE_PROTECT)
            sl = max(sl, b) if long else min(sl, b)

        # 트레일링 — 긴급TS는 TP 근처에서 K를 좁힌다
        peak = max(peak, hi) if long else min(peak, lo)
        k = EMERG_K if (emerg and gain >= tp_pct * EMERG_RATIO) else k_ch
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k * a) if long else (peak + k * a)
        sl = max(sl, ch) if long else min(sl, ch)

        # 횡보청산 — 45분 뒤 수익이 아니고 손실이 얕으면 접는다
        if timeout and j - i >= TIMEOUT_BARS:
            cur = (c[j] - e) / e if long else (e - c[j]) / e
            if cur <= 0 and cur >= -TIMEOUT_MAX_LOSS:
                out = cur * remain
                done = True
                break
        j += 1

    if not done:
        last = c[min(j, end)]
        out = ((last - e) / e if long else (e - last) / e) * remain
    return min(j, end), booked + out - FEE


def simulate(frames, sigs, gates, lo, hi, k_ch, **kw):
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        if (gates[sym][i - 1] > 0) != (s["dir"] == "long"):
            continue
        ei, p = run_trade(frames[sym], s, k_ch, **kw)
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def fmt(p):
    if not p:
        return "0건"
    w = sum(1 for x in p if x > 0)
    return f"{len(p)}건 {100*w/len(p):.0f}% {sum(p)*100:+.1f}%"


def main():
    frames = load()
    n0 = len(next(iter(frames.values())))
    mid = n0 // 2
    sigs = json.load(open(SIGCACHE))
    print(f"  {len(frames)}종목 · {n0}봉 = {n0*15/60/24:.0f}일 · 신호 "
          f"{sum(len(v) for v in sigs.values())}건 (실거래 종목군)")

    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, GATE_EMA), 1, -1)
             for s, d in frames.items()}

    cases = [
        ("현행 (전부 OFF · K=4.0)", 4.0, {}),
        ("① 본전보호 ON",           4.0, {"be": True}),
        ("② 횡보청산 ON",           4.0, {"timeout": True}),
        ("③ 분할익절 ON",           4.0, {"partial": True, "scaleout": True}),
        ("④ 긴급TS ON",             4.0, {"emerg": True}),
        ("⑤ 넷 다 ON (제거 전)",    4.0, {"be": True, "timeout": True,
                                          "partial": True, "scaleout": True,
                                          "emerg": True}),
        ("K=3.0",                   3.0, {}),
        ("K=5.0",                   5.0, {}),
    ]
    print("  " + "═" * 72)
    print(f"  {'설정':<28}{'봉인 앞90일':>21}{'개발 뒤90일':>21}")
    print("  " + "─" * 72)
    base = None
    for nm, k, kw in cases:
        a = simulate(frames, sigs, gates, 0, mid, k, **kw)
        b = simulate(frames, sigs, gates, mid, n0, k, **kw)
        if base is None:
            base = (sum(a) * 100, sum(b) * 100)
        mark = ""
        if nm.startswith(("①", "②", "③", "④", "⑤")):
            d1, d2 = sum(a) * 100 - base[0], sum(b) * 100 - base[1]
            mark = "  ← 켜면 개선" if (d1 > 0 and d2 > 0) else f"  (Δ{d1:+.1f}/{d2:+.1f})"
        print(f"  {nm:<28}{fmt(a):>21}{fmt(b):>21}{mark}")
    print("  " + "─" * 72)
    print("  판정: ①~⑤는 '켜면 개선'이 아니면 지금처럼 OFF가 옳다.")


if __name__ == "__main__":
    main()
