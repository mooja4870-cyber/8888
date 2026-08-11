#!/usr/bin/env python3
"""verify_partial_be.py — 분할익절 + 잔량 본전스톱 검증

실측 (8403, 2026-08-11) — 거래소 주문 내역으로 확인
──────────────────────────────────────────────
  DATA 숏  : 진입 0.2058 → 23:39 절반 0.2044(+0.68%) → 23:52 잔량 0.2041(+0.83%)
  PEOPLE 롱: 진입 0.008626 → 22:04 절반 0.008689(+0.73%) → 23:50 잔량 0.008634(**+0.09%**)
             보유 중 최고 +1.60%였는데 절반은 0.73%, 잔량은 사실상 본전.

원인 두 가지
  ① `USE_SCALEOUT=True`가 분할익절 임계를 설정값의 절반으로 낮춘다.
        trigger = min(PARTIAL_TP_TRIGGER_PCT, TARGET_TP_PCT × 0.5) = min(1.5%, 0.75%)
     설정 화면엔 1.5%로 보이는데 실제로는 0.75%에 나간다.
  ② 분할익절 직후 `arm_breakeven_stop()`이 잔량을 본전 스톱으로 묶는다.
     어제 끈 `USE_BE_GUARD`와는 **다른 경로**라 그대로 살아 있었다.

어제 실측에서 본전보호는 평균 승 +0.82%(켬) vs +9.18%(끔)로 승리를 잘라냈다.
같은 구조가 이름만 바꿔 남아 있었던 셈이므로, 여기서 근거를 만든다.

검증안
  ① SCALEOUT 해제  — 분할익절 임계를 설정값(1.5%)으로
  ② 본전스톱 해제  — 잔량을 본전에 묶지 않음
  ③ 분할익절 자체 해제 — 전량을 트레일링으로
두 구간(봉인=하락, 개발=상승) 모두 개선되는 것만 채택한다.
"""
import json, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/l/project/8888")
exec(open("/Users/l/project/8888/lab/verify_gate_design.py").read()
     .split("def main():")[0].replace('if __name__', '#'))

FEE = 0.001
MAX_POS = 3


def run_trade(df, s, direction, cfg, pt_trig, use_be, use_partial):
    """실거래 청산 경로 재현.

    pt_trig    : 분할익절 발동 수익률 (SCALEOUT 반영값)
    use_be     : 분할익절 후 잔량을 본전 스톱으로 묶을지
    use_partial: 분할익절 자체를 쓸지
    """
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    pt_frac = g("PARTIAL_TP_FRACTION", .5)
    k_ch = g("CHANDELIER_K", 3.0)
    hold = int(g("MAX_HOLDING_HOURS", 6.0) * 4) or 10 ** 9

    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = direction == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    realized, remain = 0.0, 1.0
    part, peak = False, e
    end = min(n - 1, i + hold)
    j, done = i, False
    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e) / e if long else (e - lo) / e

        # 손절 우선(보수적)
        if (long and lo <= sl) or (not long and hi >= sl):
            realized += remain * ((sl - e) / e if long else (e - sl) / e)
            done = True
            break

        # 분할익절 → 잔량 본전스톱(옵션)
        if use_partial and not part and gain >= pt_trig:
            realized += pt_frac * pt_trig
            remain -= pt_frac
            part = True
            peak = hi if long else lo
            if use_be:
                sl = max(sl, e) if long else min(sl, e)      # 잔량 본전 스톱
        # 잔량 트레일링(샹들리에)
        if part:
            peak = max(peak, hi) if long else min(peak, lo)
            a = atr[j] if atr[j] == atr[j] else 0.0
            ch = (peak - k_ch * a) if long else (peak + k_ch * a)
            sl = max(sl, ch) if long else min(sl, ch)
        # 거래소 TP (분할 전에만 유효)
        elif gain >= tp_pct:
            realized += remain * tp_pct
            done = True
            break
        j += 1
    if not done:
        last = c[min(j, end)]
        realized += remain * ((last - e) / e if long else (e - last) / e)
    return min(j, end), realized - FEE


def simulate(frames, sigs, gates, cfg, lo, hi, pt_trig, use_be, use_partial):
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
        ei, p = run_trade(frames[sym], s, d, cfg, pt_trig, use_be, use_partial)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
    return pnl


def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    sigs = get_signals(frames)
    cfg = dict(json.load(open(f"{BOT}/config.json"))); cfg["USE_BE_GUARD"] = False
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 48), 1, -1)
             for s, d in frames.items()}

    print("  " + "═" * 78)
    print(f"  {'설정':<36}{'봉인 앞90일(하락)':>21}{'개발 뒤90일(상승)':>21}")
    print("  " + "─" * 78)
    base = None
    variants = [
        ("현행 (0.75% 분할 + 본전스톱)",      0.0075, True,  True),
        ("① SCALEOUT 해제 (1.5% 분할)",       0.015,  True,  True),
        ("② 본전스톱 해제 (0.75% 분할)",      0.0075, False, True),
        ("①+② 1.5% 분할 · 본전스톱 없음",     0.015,  False, True),
        ("③ 분할익절 자체 해제",              0.015,  False, False),
    ]
    for nm, trig, be, pt in variants:
        cells, nets = [], []
        for a, b in ((0, mid), (mid, n0)):
            p = simulate(frames, sigs, gates, cfg, a, b, trig, be, pt)
            net = sum(p) * 100
            nets.append(net)
            wr = 100 * sum(1 for x in p if x > 0) / len(p) if p else 0
            cells.append(f"{len(p)}건 {wr:.0f}% {net:+.1f}%")
        mark = ""
        if base is None:
            base = nets
        else:
            mark = " ✅" if nets[0] > base[0] and nets[1] > base[1] else ""
        print(f"  {nm:<36}{cells[0]:>21}{cells[1]:>21}{mark}")
    print("  " + "─" * 78)
    print("  ✅ = 두 구간 모두 현행보다 개선. 이것만 채택 후보.")


if __name__ == "__main__":
    main()
