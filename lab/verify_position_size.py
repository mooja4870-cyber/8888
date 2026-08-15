#!/usr/bin/env python3
"""verify_position_size.py — 복리 비율(진입 증거금 %)이 최적인지

이건 시장 예측이 아니라 산수다. 같은 거래 순서에 배팅 크기만 바꿔 굴리면
최적 비율이 나온다. 켈리 기준이 다루는 문제다.

핵심 긴장
─────────
  · 크게 걸면 복리로 빨리 불지만, 연속 손실에 계좌가 깎여 회복이 어려워진다
  · 작게 걸면 안전하지만 수수료 대비 수익이 얇아진다
  · **기하평균 수익**은 어느 지점에서 최대가 되고, 그 지점을 넘으면 오히려 줄어든다

현재 설정은 잔고의 15%를 증거금으로, 최대 3포지션(=최대 45% 노출)이다.
레버리지 5배이므로 명목 노출은 잔고의 최대 225%다.

방법
────
실제 거래 손익 수열(검증된 조건: 게이트 ON·승리절단 해제·K는 TF별)을 그대로 쓰고,
배팅 비율만 바꿔 잔고를 순차 복리로 굴린다. 최대낙폭도 함께 본다.
거래 순서를 무작위로 섞어 여러 번 돌려 **순서 운**의 영향도 확인한다.
"""
import json, random, statistics, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/l/project/8888")
exec(open("/Users/l/project/8888/lab/verify_gate_design.py").read()
     .split("def main():")[0].replace('if __name__', '#'))

FEE = 0.001
MAX_POS = 3
LEV = 5


def run_trade(df, s, direction, cfg, k_ch=4.0):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values; n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    hold = int(g("MAX_HOLDING_HOURS", 6.0) * 4) or 10 ** 9
    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = direction == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak = e; end = min(n - 1, i + hold)
    j, done, out = i, False, 0.0
    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e)/e if long else (e - lo)/e
        if (long and lo <= sl) or (not long and hi >= sl):
            out = (sl - e)/e if long else (e - sl)/e; done = True; break
        if gain >= tp_pct:
            out = tp_pct; done = True; break
        peak = max(peak, hi) if long else min(peak, lo)
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k_ch*a) if long else (peak + k_ch*a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if not done:
        last = c[min(j, end)]
        out = (last - e)/e if long else (e - last)/e
    return min(j, end), out - FEE


def collect(frames, sigs, gates, cfg, lo, hi):
    """가격 변동률 수열(진입 증거금 대비가 아니라 **가격** 기준)."""
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, out = {}, [], []
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        d = s["dir"]
        if (gates[sym][i - 1] > 0) != (d == "long"):
            continue
        ei, p = run_trade(frames[sym], s, d, cfg)
        out.append(p); busy[sym] = ei; openp.append(ei)
    return out


def compound(moves, pct, lev=LEV):
    """배팅 비율 pct(잔고 대비 증거금)로 순차 복리. (최종배수, 최대낙폭)"""
    bal, peak, mdd = 1.0, 1.0, 0.0
    for m in moves:
        bal *= (1 + pct * lev * m)          # 증거금×레버 = 명목, 명목×가격변동 = 손익
        if bal <= 0:
            return 0.0, 1.0
        peak = max(peak, bal)
        mdd = max(mdd, (peak - bal) / peak)
    return bal, mdd


def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    sigs = get_signals(frames)
    cfg = dict(json.load(open(f"{BOT}/config.json")))
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 48), 1, -1)
             for s, d in frames.items()}

    segs = {"봉인(하락)": collect(frames, sigs, gates, cfg, 0, mid),
            "개발(상승)": collect(frames, sigs, gates, cfg, mid, n0)}
    for k, v in segs.items():
        w = 100*sum(1 for x in v if x > 0)/len(v) if v else 0
        print(f"  {k}: {len(v)}건 · 승률 {w:.0f}% · 평균 가격변동 {statistics.mean(v)*100:+.3f}%")
    print("  " + "═" * 70)
    print(f"  {'증거금 비율':<14}" + "".join(f"{s+' 최종/MDD':>22}" for s in segs))
    print("  " + "─" * 70)
    best = {}
    for pct in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
        cells = []
        for name, moves in segs.items():
            bal, mdd = compound(moves, pct)
            cells.append(f"×{bal:.2f} / -{mdd*100:.0f}%")
            best.setdefault(name, []).append((bal, pct))
        mark = "  ← 현행" if abs(pct - 0.15) < 1e-9 else ""
        print(f"  {pct*100:>10.0f}%  " + "".join(f"{c:>22}" for c in cells) + mark)
    print("  " + "─" * 70)
    for name, lst in best.items():
        b = max(lst)
        print(f"  {name} 최적 비율: {b[1]*100:.0f}% (×{b[0]:.2f})")

    # 순서 운 확인 — 무작위 셔플 200회
    print("\n  ■ 거래 순서를 섞었을 때 (200회, 중앙값)")
    print(f"  {'비율':<10}" + "".join(f"{s:>20}" for s in segs))
    print("  " + "─" * 60)
    for pct in (0.10, 0.15, 0.20, 0.30):
        cells = []
        for name, moves in segs.items():
            outs = []
            for _ in range(200):
                mv = moves[:]
                random.shuffle(mv)
                b, _m = compound(mv, pct)
                outs.append(b)
            cells.append(f"×{statistics.median(outs):.2f}")
        print(f"  {pct*100:>6.0f}%   " + "".join(f"{c:>20}" for c in cells))


if __name__ == "__main__":
    main()
