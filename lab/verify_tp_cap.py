#!/usr/bin/env python3
"""verify_tp_cap.py — 거래소 TP가 승리를 막고 있는가

실거래 관찰 (2026-08-16, 거래소 원장)
────────────────────────────────────
| 봇 | 전략 | 손익비 | 최대 승 |
|:--|:--|--:|--:|
| 8408·8409 | 이중볼린저 | **3.0~3.9** | $1.55~1.62 |
| 8401·8403 | MFI | **1.09~1.17** | $0.35 |

MFI 2봇만 승리가 자라지 못한다. 원인을 역산하니 TP였다.
  8403 최대 승 $0.3579 → 증거금 대비 ROI 8.1% → 가격 1.63%
  DIV_TP_RR=1.5 × 손절폭 1.1% = TP 1.65%   ← 정확히 일치

즉 트레일링이 승리를 끌어주기 전에 **고정 TP가 먼저 체결**된다.
이번 주 여섯 번 확인한 '조기 청산하지 마라'의 일곱 번째 후보다.

검증안
──────
① TP 손익비 상향 (RR ×1.5 / ×2.5)
② **TP 제거** — 청산을 손절 + 샹들리에 트레일링에만 맡긴다 (가장 순수한 형태)
③ TP를 트레일링 시작점으로 (TP 도달 후에도 계속 끌기)

두 구간 모두 개선되는 것만 채택한다. TP 제거는 위험할 수 있으므로
최대낙폭과 거래당 최악값도 함께 본다.
"""
import json, statistics, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/l/project/8888")
exec(open("/Users/l/project/8888/lab/verify_gate_design.py").read()
     .split("def main():")[0].replace('if __name__', '#'))

FEE = 0.001
MAX_POS = 3
K_BASE = 4.0            # 15분봉 채택값


def run_trade(df, s, direction, cfg, mode, rr_mult=1.0):
    """mode: 'tp'(현행) · 'none'(TP 제거) · 'trail'(TP 도달 후 트레일 계속)"""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    hold = int(g("MAX_HOLDING_HOURS", 6.0) * 4) or 10 ** 9
    i, e, risk, rr0 = s["i"], s["e"], s["risk"], s["rr"]
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
        if mode == "tp" and gain >= tp_pct:
            out = tp_pct
            done = True
            break
        peak = max(peak, hi) if long else min(peak, lo)
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - K_BASE * a) if long else (peak + K_BASE * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if not done:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), out - FEE


def simulate(frames, sigs, gates, cfg, lo, hi, mode, rr_mult=1.0):
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
        ei, p = run_trade(frames[sym], s, d, cfg, mode, rr_mult)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
    return pnl


def stats(p):
    if not p:
        return "0건"
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    pf = (abs(statistics.mean(w) / statistics.mean(l)) if w and l else 0)
    # 누적 최대낙폭
    bal, pk, mdd = 1.0, 1.0, 0.0
    for x in p:
        bal *= (1 + 0.15 * 5 * x)
        pk = max(pk, bal); mdd = max(mdd, (pk - bal) / pk)
    return (f"{len(p)}건 {100*len(w)/len(p):.0f}% {sum(p)*100:+.1f}% "
            f"손익비{pf:.2f} MDD-{mdd*100:.0f}%")


def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    sigs = get_signals(frames)
    cfg = dict(json.load(open(f"{BOT}/config.json")))
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 48), 1, -1)
             for s, d in frames.items()}
    print("  " + "═" * 92)
    print(f"  {'설정':<24}{'봉인 앞90일(하락)':>34}{'개발 뒤90일(상승)':>34}")
    print("  " + "─" * 92)
    base = None
    for nm, mode, rr in (("현행 TP (RR 그대로)", "tp", 1.0),
                         ("TP 손익비 ×1.5", "tp", 1.5),
                         ("TP 손익비 ×2.5", "tp", 2.5),
                         ("TP 제거 (트레일만)", "none", 1.0)):
        cells, nets = [], []
        for a, b in ((0, mid), (mid, n0)):
            p = simulate(frames, sigs, gates, cfg, a, b, mode, rr)
            nets.append(sum(p) * 100)
            cells.append(stats(p))
        mark = ""
        if base is None:
            base = nets
        else:
            mark = "  ✅" if nets[0] > base[0] and nets[1] > base[1] else ""
        print(f"  {nm:<24}{cells[0]:>34}{cells[1]:>34}{mark}")
    print("  " + "─" * 92)
    print("  MDD는 증거금 15%·레버 5배로 순차 복리했을 때의 최대낙폭.")


if __name__ == "__main__":
    main()
