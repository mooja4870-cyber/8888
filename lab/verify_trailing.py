#!/usr/bin/env python3
"""verify_trailing.py — 트레일링이 TP를 무력화하는 문제 검증

실측 (8403, 2026-08-11)
──────────────────────
  DATA 숏 : TP +1.00% · 트레일 발동 +1.00% · 콜백 0.80%
            가격이 +1.02%까지 가서 **TP선에 닿았는데** 트레일링이 먼저 끊어 +0.85% 청산.
  PEOPLE 롱: TP +2.48% · 트레일 발동 +1.26% · 콜백 1.26%
            +1.60%까지 갔다가 +0.43%에 청산. 벌어둔 것의 73%를 반납.

원인은 세 장치가 같은 구간에서 경합하는 것이다.
  ① 거래소 TP 주문   ② ATR 트레일링   ③ 분할익절(+1.5%)
특히 DATA는 TP와 트레일 발동이 정확히 같은 +1.00%라 TP가 영원히 체결될 수 없다.

실거래 산식(core/trader.py:766~773)
  발동 = clamp(atr_pct × 1.5, 1.0%, 5.0%)
  콜백 = clamp(atr_pct × 1.3, 0.8%, 3.0%)

검증안
  A) 발동을 TP 위로 — 트레일링이 TP를 앞지르지 못하게 한다(TP 도달 후에만 트레일링).
  B) 콜백 축소 — 반납 폭을 줄인다.
두 구간(봉인=하락, 개발=상승) 모두 개선되는 것만 채택한다.
"""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/l/project/8888")
exec(open("/Users/l/project/8888/lab/verify_gate_design.py").read()
     .split("def main():")[0].replace('if __name__', '#'))

FEE = 0.001
MAX_POS = 3


def run_trade(df, s, direction, cfg, act_mode, cb_mult):
    """실거래 청산 경로 재현: 거래소 TP/SL + 분할익절 + ATR 트레일링.

    act_mode: "atr"    = 현행(발동 = ATR×1.5, 1~5% 클램프)
              "afterTP"= 개선안 A(TP 도달 이후에만 트레일링 시작)
    cb_mult : 콜백 배수(현행 1.3)
    """
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    pt_on = bool(cfg.get("USE_PARTIAL_TP", True))
    pt_trig, pt_frac = g("PARTIAL_TP_TRIGGER_PCT", .015), g("PARTIAL_TP_FRACTION", .5)
    hold = int(g("MAX_HOLDING_HOURS", 6.0) * 4) or 10 ** 9

    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = direction == "long"
    a0 = atr[i] if atr[i] == atr[i] else 0.0
    atr_pct = (a0 / e) if e else 0.0
    act = max(0.010, min(0.05, atr_pct * 1.5))
    cb = max(0.008, min(0.03, atr_pct * cb_mult))
    tp_pct = risk * rr

    sl_p = e * (1 - risk) if long else e * (1 + risk)
    tp_p = e * (1 + tp_pct) if long else e * (1 - tp_pct)
    realized, remain = 0.0, 1.0
    part, armed, peak = False, False, 0.0
    end = min(n - 1, i + hold)
    j, done = i, False
    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e) / e if long else (e - lo) / e     # 봉 내 최대 유리
        loss = (lo - e) / e if long else (e - hi) / e     # 봉 내 최대 불리

        # 손절 우선(보수적)
        if loss <= -risk:
            realized += remain * (-risk)
            done = True
            break

        # 트레일링 발동 조건
        trigger = tp_pct if act_mode == "afterTP" else act
        if not armed and gain >= trigger:
            armed, peak = True, gain
        if armed:
            peak = max(peak, gain)
            # 되돌림이 콜백을 넘으면 청산 (봉 종가 기준 보수적 판정)
            cur = (c[j] - e) / e if long else (e - c[j]) / e
            if peak - cur >= cb:
                realized += remain * max(cur, 0.0)
                done = True
                break

        # 거래소 TP — 트레일링이 아직 안 걸렸을 때만 유효(실거래에서 경합해 밀림)
        if not armed and gain >= tp_pct:
            realized += remain * tp_pct
            done = True
            break
        # TP 도달 후 트레일링 모드에서는 TP가 청산이 아니라 트레일 시작점이 된다

        if pt_on and not part and gain >= pt_trig:
            realized += pt_frac * pt_trig
            remain -= pt_frac
            part = True
        j += 1
    if not done:
        last = c[min(j, end)]
        realized += remain * ((last - e) / e if long else (e - last) / e)
    return min(j, end), realized - FEE


def simulate(frames, sigs, gates, cfg, lo, hi, act_mode, cb_mult):
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
        ei, p = run_trade(frames[sym], s, d, cfg, act_mode, cb_mult)
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

    print("  " + "═" * 76)
    print(f"  {'설정':<34}{'봉인 앞90일(하락)':>21}{'개발 뒤90일(상승)':>21}")
    print("  " + "─" * 76)
    base = None
    for nm, mode, cb in (("현행 (발동 ATR×1.5 · 콜백 ×1.3)", "atr", 1.3),
                         ("B  콜백 축소 ×0.8",              "atr", 0.8),
                         ("B  콜백 축소 ×0.5",              "atr", 0.5),
                         ("A  TP 도달 후 트레일 (콜백 ×1.3)", "afterTP", 1.3),
                         ("A+B TP 후 트레일 · 콜백 ×0.8",    "afterTP", 0.8),
                         ("A+B TP 후 트레일 · 콜백 ×0.5",    "afterTP", 0.5)):
        cells, nets = [], []
        for a, b in ((0, mid), (mid, n0)):
            p = simulate(frames, sigs, gates, cfg, a, b, mode, cb)
            net = sum(p) * 100
            nets.append(net)
            wr = 100 * sum(1 for x in p if x > 0) / len(p) if p else 0
            cells.append(f"{len(p)}건 {wr:.0f}% {net:+.1f}%")
        if base is None:
            base = nets
            mark = ""
        else:
            mark = " ✅" if nets[0] > base[0] and nets[1] > base[1] else ""
        print(f"  {nm:<34}{cells[0]:>21}{cells[1]:>21}{mark}")
    print("  " + "─" * 76)
    print("  ✅ = 두 구간 모두 현행보다 개선. 이것만 채택 후보.")


if __name__ == "__main__":
    main()
