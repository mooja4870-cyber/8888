#!/usr/bin/env python3
"""verify_loss_side.py — 손실 쪽 대칭 검증

이번 주에 통과한 4가지 조치는 전부 "승리를 자르지 마라"였다
(본전보호·45분 횡보청산·분할익절·긴급 트레일링 해제).
그런데 **손실 쪽은 한 번도 검증하지 않았다.**

승리를 끝까지 끌게 만들었으면, 손실은 어떻게 다뤄야 하는가?
  · 손절이 너무 좁으면 정상 흔들림에 털리고(승률↓, 손실 잦음)
  · 너무 넓으면 한 방이 크다
  · 트레일링 K도 같은 딜레마 — 좁으면 조기청산, 넓으면 반납

세 변수를 격자로 훑어 국면이 정반대인 두 구간 **모두** 개선되는 조합만 채택한다.
한쪽에서만 좋으면 국면 의존이므로 기각한다(이번 주 내내 쓴 기준).

주의: 승리 절단 장치는 이미 전부 해제된 상태를 기준선으로 삼는다.
"""
import json, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/l/project/8888")
exec(open("/Users/l/project/8888/lab/verify_gate_design.py").read()
     .split("def main():")[0].replace('if __name__', '#'))

FEE = 0.001
MAX_POS = 3


def run_trade(df, s, direction, cfg, sl_mult, k_ch, rr_mult):
    """sl_mult: 손절폭 배수(1.0=현행) · k_ch: 샹들리에 K · rr_mult: 손익비 배수"""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    hold = int(g("MAX_HOLDING_HOURS", 6.0) * 4) or 10 ** 9

    i, e, risk0, rr0 = s["i"], s["e"], s["risk"], s["rr"]
    risk = risk0 * sl_mult
    rr = rr0 * rr_mult
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
        peak = max(peak, hi) if long else min(peak, lo)
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k_ch * a) if long else (peak + k_ch * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if not done:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), out - FEE


def simulate(frames, sigs, gates, cfg, lo, hi, sl_mult, k_ch, rr_mult):
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
        ei, p = run_trade(frames[sym], s, d, cfg, sl_mult, k_ch, rr_mult)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
    return pnl


def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    sigs = get_signals(frames)
    cfg = dict(json.load(open(f"{BOT}/config.json")))
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 48), 1, -1)
             for s, d in frames.items()}

    def run(sl, k, rr):
        cells, nets = [], []
        for a, b in ((0, mid), (mid, n0)):
            p = simulate(frames, sigs, gates, cfg, a, b, sl, k, rr)
            net = sum(p) * 100
            nets.append(net)
            wr = 100 * sum(1 for x in p if x > 0) / len(p) if p else 0
            cells.append(f"{len(p)}건 {wr:.0f}% {net:+.1f}%")
        return cells, nets

    base_cells, base = run(1.0, 3.0, 1.0)
    print("  " + "═" * 74)
    print(f"  {'설정':<30}{'봉인 앞90일(하락)':>22}{'개발 뒤90일(상승)':>22}")
    print("  " + "─" * 74)
    print(f"  {'현행 (SL×1.0 K=3.0 RR×1.0)':<30}{base_cells[0]:>22}{base_cells[1]:>22}")
    print("  " + "─" * 74)

    tests = []
    for sl in (0.7, 1.0, 1.5, 2.0):
        tests.append((f"손절폭 ×{sl}", sl, 3.0, 1.0))
    for k in (1.5, 2.0, 4.0, 6.0):
        tests.append((f"트레일 K={k}", 1.0, k, 1.0))
    for rr in (0.7, 1.5, 2.0):
        tests.append((f"손익비 ×{rr}", 1.0, 3.0, rr))

    winners = []
    for nm, sl, k, rr in tests:
        cells, nets = run(sl, k, rr)
        ok = nets[0] > base[0] and nets[1] > base[1]
        if ok:
            winners.append((nm, sl, k, rr, nets))
        print(f"  {nm:<30}{cells[0]:>22}{cells[1]:>22}{'  ✅' if ok else ''}")
    print("  " + "─" * 74)
    print(f"  두 구간 모두 개선: {[w[0] for w in winners] or '없음'}")

    if winners:
        print("\n  ■ 상위 조합 교차 검증")
        print("  " + "─" * 74)
        for nm, sl, k, rr, _ in winners[:3]:
            for nm2, sl2, k2, rr2, _ in winners[:3]:
                if nm == nm2:
                    continue
                s2, k3, r3 = sl * sl2, (k if k != 3.0 else k2), rr * rr2
                cells, nets = run(s2, k3, r3)
                ok = nets[0] > base[0] and nets[1] > base[1]
                if ok:
                    print(f"  {nm}+{nm2:<20}{cells[0]:>22}{cells[1]:>22}  ✅")
                break


if __name__ == "__main__":
    main()
