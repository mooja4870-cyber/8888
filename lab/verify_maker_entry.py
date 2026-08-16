#!/usr/bin/env python3
"""verify_maker_entry.py — 지정가(메이커) 진입이 시장가(테이커)보다 나은가

왜 이걸 보는가
─────────────
실측 수수료는 건당 **0.101%**인데 백테스트 기대 엣지는 **+0.057%**다.
**비용이 엣지의 1.8배**다. 이 상태에서 파라미터를 만지는 건 의미가 없다
(K 3.0 vs 4.0 차이 0.001%p). 비용을 줄이는 쪽이 크고 확실하다.

perp 수수료 (OKX·바이낸스 VIP0 동일)
  메이커 0.02% / 테이커 0.05%
따라서 왕복 비용은 **청산 방식에 따라 다르다**:
  · 진입 지정가 + TP 지정가       = 0.04%
  · 진입 지정가 + 손절/트레일 시장가 = 0.07%
  · 전부 시장가 (현행)            = 0.10%
이 스크립트는 이 셋을 뭉뚱그리지 않고 **청산 유형별로** 계산한다.

공짜가 아니다
────────────
지정가는 체결이 안 될 수 있고, 안 되면 그 신호를 놓친다. 그리고 **놓치는 신호는
무작위가 아니다** — 값이 곧장 내 방향으로 가버린 경우, 즉 좋은 신호일수록 못 산다.
그래서 절감분과 기회손실을 함께 재야 한다. 체결률만 보고 판단하면 틀린다.

채택 조건: 두 구간(봉인·개발) 모두 현행(전부 시장가)보다 나을 것.
"""
import glob, json, os
import numpy as np, pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_live"
SIGCACHE = "/Users/l/project/8888/lab/_sigcache_8403_live61.json"
MAX_POS, HOLD, GATE_EMA, K_CH = 3, 24, 48, 4.0

FEE_MAKER, FEE_TAKER = 0.0002, 0.0005


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


def try_fill(df, i, e, long, offset, wait):
    """지정가 체결 시도. 반환 (체결봉, 체결가) 또는 (None, None).

    롱이면 진입가보다 offset만큼 **낮은** 가격에 매수 주문을 건다.
    이후 wait봉 안에 저가가 그 가격을 찍으면 체결로 본다.
    """
    lim = e * (1 - offset) if long else e * (1 + offset)
    lo, hi = df["low"].values, df["high"].values
    n = len(lo)
    for j in range(i, min(i + wait + 1, n)):
        if (long and lo[j] <= lim) or (not long and hi[j] >= lim):
            return j, lim
    return None, None


def run_trade(df, i, e, risk, rr, long, maker_entry):
    """청산까지 굴린다. 반환 (청산봉, 순수익률).

    수수료는 진입 방식과 청산 유형에 따라 따로 붙인다.
    """
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(c)
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak = e
    end = min(n - 1, i + HOLD)
    fee_in = FEE_MAKER if maker_entry else FEE_TAKER
    j, out, fee_out = i, None, FEE_TAKER

    while j <= end:
        gain = (h[j] - e) / e if long else (e - l[j]) / e
        if (long and l[j] <= sl) or (not long and h[j] >= sl):
            out = (sl - e) / e if long else (e - sl) / e
            fee_out = FEE_TAKER                      # 손절·트레일 = 시장가
            break
        if gain >= tp_pct:
            out = tp_pct
            fee_out = FEE_MAKER                      # 익절 = 지정가
            break
        peak = max(peak, h[j]) if long else min(peak, l[j])
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - K_CH * a) if long else (peak + K_CH * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1

    if out is None:                                  # 시간 만료 = 시장가
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
        fee_out = FEE_TAKER
    return min(j, end), out - fee_in - fee_out


def simulate(frames, sigs, gates, lo, hi, mode, offset=0.0, wait=0):
    """mode: 'taker' | 'maker'"""
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    seen = filled = 0
    for i, sym, s in allsig:
        openp = [x for x in openp if x > i]
        if busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        long = s["dir"] == "long"
        if (gates[sym][i - 1] > 0) != long:
            continue
        seen += 1
        df = frames[sym]
        if mode == "taker":
            ei, e = i, s["e"]
        else:
            ei, e = try_fill(df, i, s["e"], long, offset, wait)
            if ei is None:
                continue                              # 미체결 → 신호 포기
        filled += 1
        cj, p = run_trade(df, ei, e, s["risk"], s["rr"], long, mode == "maker")
        pnl.append(p)
        busy[sym] = cj
        openp.append(cj)
    return pnl, seen, filled


def fmt(pnl, seen, filled):
    if not pnl:
        return f"{filled}/{seen}건  0%"
    w = sum(1 for x in pnl if x > 0)
    return (f"{filled:>4}/{seen:<4} 체결{100*filled/seen:>3.0f}%  "
            f"승{100*w/len(pnl):>3.0f}%  {sum(pnl)*100:+7.1f}%  "
            f"건당{sum(pnl)/len(pnl)*100:+.4f}%")


def main():
    frames = load()
    n0 = len(next(iter(frames.values())))
    mid = n0 // 2
    sigs = json.load(open(SIGCACHE))
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, GATE_EMA), 1, -1)
             for s, d in frames.items()}
    print(f"  {len(frames)}종목 · {n0*15/60/24:.0f}일 · 신호 {sum(len(v) for v in sigs.values())}건")
    print(f"  메이커 {FEE_MAKER*100:.2f}% · 테이커 {FEE_TAKER*100:.2f}% "
          f"(청산 유형별로 따로 계산: TP=지정가, 손절·트레일·시간=시장가)")
    print("  " + "═" * 96)
    print(f"  {'설정':<30}{'봉인 앞90일':>33}{'개발 뒤90일':>33}")
    print("  " + "─" * 96)

    cases = [("현행 · 전부 시장가", "taker", 0.0, 0)]
    for off in (0.0, 0.0005, 0.0010):
        for wait in (1, 2, 4):
            cases.append((f"지정가 {off*100:.2f}% 유리 · {wait}봉 대기", "maker", off, wait))

    base = None
    for nm, mode, off, wait in cases:
        cells = []
        for a, b in ((0, mid), (mid, n0)):
            pnl, seen, filled = simulate(frames, sigs, gates, a, b, mode, off, wait)
            cells.append((fmt(pnl, seen, filled), sum(pnl) * 100))
        if base is None:
            base = (cells[0][1], cells[1][1])
            mark = "  기준"
        else:
            d1, d2 = cells[0][1] - base[0], cells[1][1] - base[1]
            mark = "  ← 양쪽 개선" if (d1 > 0 and d2 > 0) else f"  (Δ{d1:+.1f}/{d2:+.1f})"
        print(f"  {nm:<30}{cells[0][0]:>33}{cells[1][0]:>33}{mark}")
    print("  " + "─" * 96)
    print("  주의: 미체결로 놓치는 신호는 무작위가 아니다 — 값이 곧장 내 방향으로")
    print("        간 경우(좋은 신호)일수록 못 산다. 체결률만 보고 판단하면 틀린다.")


if __name__ == "__main__":
    main()
