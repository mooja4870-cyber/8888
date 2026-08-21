#!/usr/bin/env python3
"""verify_auto_reverse.py — 자동 역매매 전환(5전 3패 → 반전)이 유의미한가

무엇을 검증하나
──────────────
같은 전략에서 신호가 롱일 때
  · 순방향 = 롱으로 진입
  · 역방향 = 숏으로 진입 (신호 반대로)
봇에는 **최근 5건 중 3건 이상 손실이면 자동으로 역방향으로 뒤집는** 기능이 있다
(`USE_AUTO_MODE_SWITCH`). 현재는 꺼져 있다 — 30일간 8번(평균 3.75일 주기) 방향이
뒤집혀 측정이 불가능했기 때문이다.

이 방식 자체가 유의미한지 3년 자료로 가린다.

왜 특히 의심스러운가
──────────────────
과거 성적으로 미래 방향을 정하는 방식이다. 성적이 나쁜 건 대부분 **운**이므로,
운에 반응해 방향을 뒤집으면 잡음을 좇게 된다. 게다가 뒤집을 때마다 수수료를 문다.
그래서 6분할 검증을 그대로 건다 — 한 구간이 전부를 만들면 가짜다.

비교 대상
  · 순방향 고정
  · 역방향 고정
  · 자동 전환 (3전2패 / 5전3패 / 10전6패)
"""
import sys
import numpy as np

sys.path.insert(0, "/Users/l/project/8888/lab")
from sweep_4h_long import (load, sig_donchian, sig_double_bb, sig_xmom,
                           run_trade, stat, BARS_DAY, MAX_POS)


def simulate(frames, sigmap, lo, hi, sl_mult, rr, k_ch, hold, mode, win_n=5, loss_k=3):
    """mode: 'fwd' | 'rev' | 'auto'

    auto는 봉이 아니라 **청산 순서**로 판정한다. 봇이 청산 직후에 검사하기 때문이다.
    진입 시점 t 이전에 이미 청산된 거래들 중 최근 win_n건을 보고, 손실이 loss_k건
    이상이면 방향을 뒤집는다.
    """
    allsig = sorted(((t, s, d) for s, v in sigmap.items() for t, d in v
                     if lo <= t < hi), key=lambda x: x[0])
    busy, openp, pnl = {}, [], []
    closed = []                      # (청산봉, 손익) — 청산 순서 판정용
    reversed_now = False
    flips = 0

    for t, sym, d in allsig:
        openp = [x for x in openp if x > t]
        if busy.get(sym, -1) >= t or len(openp) >= MAX_POS:
            continue

        if mode == "auto":
            done = sorted([c for c in closed if c[0] <= t], key=lambda x: x[0])
            if len(done) >= win_n:
                last = done[-win_n:]
                losses = sum(1 for _, p in last if p <= 0)
                want = losses >= loss_k
                if want != reversed_now:
                    reversed_now = want
                    flips += 1
            use_rev = reversed_now
        else:
            use_rev = (mode == "rev")

        dd = d if not use_rev else ("short" if d == "long" else "long")
        ei, p = run_trade(frames[sym], t, dd, sl_mult, rr, k_ch, hold)
        if p is None:
            continue
        pnl.append(p)
        closed.append((ei, p))
        busy[sym] = ei
        openp.append(ei)
    return pnl, flips


def fmt(s, flips=None):
    if s is None:
        return "표본부족"
    x = f"{s['n']:>4}건 승{s['win']:>2.0f}% {s['mean']:+.3f}±{s['se']:.3f}"
    if flips is not None:
        x += f" 전환{flips}회"
    return x


def main():
    frames = load()
    n0 = len(next(iter(frames.values())))
    mid = n0 // 2
    q = n0 // 6
    print(f"  {len(frames)}종목 · {n0}봉 = {n0/BARS_DAY/365:.1f}년 (4시간봉)")
    print("  순방향=신호대로 · 역방향=신호 반대 · 자동=최근 N건 중 K건 손실이면 반전")

    strat = {
        "돈치안12": {s: sig_donchian(d, 12) for s, d in frames.items()},
        "돈치안60": {s: sig_donchian(d, 60) for s, d in frames.items()},
        "이중볼린저": {s: sig_double_bb(d) for s, d in frames.items()},
        "모멘텀60": sig_xmom(frames, 60, 12, 8),
    }
    SL, RR, K, HOLD = 2.0, 1.5, 4.0, 12

    print(f"\n  손절ATR{SL} · RR{RR} · K{K} · 보유{HOLD}봉")
    print("  " + "═" * 96)
    print(f"  {'전략':<12}{'방향':<16}{'봉인 앞1.5년':>28}{'개발 뒤1.5년':>28}{'6분할':>8}")
    print("  " + "─" * 96)

    keep = []
    for name, sm in strat.items():
        for label, mode, wn, lk in (("순방향 고정", "fwd", 0, 0),
                                    ("역방향 고정", "rev", 0, 0),
                                    ("자동 3전2패", "auto", 3, 2),
                                    ("자동 5전3패", "auto", 5, 3),
                                    ("자동 10전6패", "auto", 10, 6)):
            pa, fa = simulate(frames, sm, 0, mid, SL, RR, K, HOLD, mode, wn, lk)
            pb, fb = simulate(frames, sm, mid, n0, SL, RR, K, HOLD, mode, wn, lk)
            a, b = stat(pa), stat(pb)
            wins = 0
            for k in range(6):
                pc, _ = simulate(frames, sm, k * q, (k + 1) * q, SL, RR, K, HOLD,
                                 mode, wn, lk)
                c = stat(pc)
                if c and c["mean"] > 0:
                    wins += 1
            ok = a and b and a["mean"] > 0 and b["mean"] > 0 and wins >= 4
            mark = "  ★" if ok else ""
            fl = (fa, fb) if mode == "auto" else (None, None)
            print(f"  {name:<12}{label:<16}{fmt(a, fl[0]):>28}{fmt(b, fl[1]):>28}"
                  f"{wins:>6}/6{mark}", flush=True)
            if ok:
                keep.append((name, label, a, b, wins))
        print("  " + "·" * 96)

    print("\n  ■ 채택 후보 (양 구간 플러스 + 6분할 4칸 이상)")
    if not keep:
        print("    없음 — 전부 기각")
    else:
        for name, label, a, b, w in sorted(keep, key=lambda x: -(x[2]["mean"] + x[3]["mean"])):
            sa, sb = a["mean"] / a["se"], b["mean"] / b["se"]
            print(f"    {name:<12}{label:<14} 봉인 {a['mean']:+.3f}±{a['se']:.3f}({sa:.2f}σ) / "
                  f"개발 {b['mean']:+.3f}±{b['se']:.3f}({sb:.2f}σ) · {w}/6")
        print("\n    ※ 2σ 미만이면 0과 구분되지 않는다 — 통과했어도 쓸 수 없다.")


if __name__ == "__main__":
    main()
