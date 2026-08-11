#!/usr/bin/env python3
"""verify_timeout_exit.py — 45분 횡보청산이 성과에 미치는 영향 재검증

경위
────
실거래 첫 거래(8403 ALLO·NEAR)가 TP 1.77% 대비 0.24%에서 잘렸다. 범인은
`USE_TIMEOUT_EXIT`(45분 안에 +0.3% 못 벌면 시장가 청산)였는데, 이 장치는
어제 검증(simulate_real)에 **들어 있지 않았다**. 즉 검증한 전략과 실제로 돌던
전략이 달랐다.

그래서 이 장치를 모델에 넣고, 어제 결론이 여전히 유효한지 확인한다.
비교는 어제와 같은 방식 — 진입 신호는 고정하고 청산만 바꾼다.
국면이 정반대인 두 구간(봉인=하락, 개발=상승)에서 모두 나빠져야
'제거가 옳다'고 말할 수 있다.

시간청산 재현
────────────
15분봉이므로 45분 = 3봉. 진입 후 3봉이 지난 시점에 손익이
-0.5% ~ +0.3% 구간이면 그 봉 종가로 청산한다(실거래 로직과 동일).
"""
import glob, json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/l/project/8888")
exec(open("/Users/l/project/8888/lab/verify_gate_design.py").read()
     .split("def main():")[0].replace('if __name__', '#'))

TIMEOUT_BARS = 3        # 45분 ÷ 15분봉
TIMEOUT_LO, TIMEOUT_HI = -0.005, 0.003


def simulate_with_timeout(sigs, df, cfg, timeout=True):
    """simulate_real과 같은 경로에 45분 횡보청산을 얹는다."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    be_on = bool(cfg.get("USE_BE_GUARD", False))
    be_trig, be_prot = g("BE_GUARD_TRIGGER_PCT", .012), g("BE_GUARD_PROTECT_PCT", .001)
    pt_on = bool(cfg.get("USE_PARTIAL_TP", True))
    pt_trig, pt_frac = g("PARTIAL_TP_TRIGGER_PCT", .015), g("PARTIAL_TP_FRACTION", .5)
    k_ch = g("CHANDELIER_K", 3.0)
    hold = int(g("MAX_HOLDING_HOURS", 6.0) * 4) or 10**9      # 15분봉 → 시간×4

    out, busy = [], -1
    for s in sigs:
        i = s["i"]
        if i <= busy:
            continue
        e, risk, rr = s["e"], s["risk"], s["rr"]
        long = s["dir"] == "long"
        sl = e * (1 - risk) if long else e * (1 + risk)
        tp = e * (1 + risk * rr) if long else e * (1 - risk * rr)
        realized, remain = 0.0, 1.0
        part, trail, peak = False, False, e
        end = min(n - 1, i + hold)
        j, done = i, False
        while j <= end:
            hi, lo = h[j], l[j]
            gain = (hi - e) / e if long else (e - lo) / e
            if be_on and gain >= be_trig:
                sl = max(sl, e * (1 + be_prot)) if long else min(sl, e * (1 - be_prot))
            if pt_on and not part and gain >= pt_trig:
                realized += pt_frac * pt_trig
                remain -= pt_frac
                part, trail, peak = True, True, (hi if long else lo)
            if trail:
                peak = max(peak, hi) if long else min(peak, lo)
                a = atr[j] if atr[j] == atr[j] else 0.0
                ch = (peak - k_ch * a) if long else (peak + k_ch * a)
                sl = max(sl, ch) if long else min(sl, ch)
            if (long and lo <= sl) or (not long and hi >= sl):
                realized += remain * ((sl - e) / e if long else (e - sl) / e)
                done = True
                break
            if not part and ((long and hi >= tp) or (not long and lo <= tp)):
                realized += remain * (risk * rr)
                done = True
                break
            # ── 45분 횡보청산 ──
            if timeout and not part and j == i + TIMEOUT_BARS:
                mv = (c[j] - e) / e if long else (e - c[j]) / e
                if TIMEOUT_LO <= mv <= TIMEOUT_HI:
                    realized += remain * mv
                    done = True
                    break
            j += 1
        if not done:
            last = c[min(j, end)]
            realized += remain * ((last - e) / e if long else (e - last) / e)
        out.append(realized)
        busy = min(j, end)
    return out


def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    sigs = get_signals(frames)
    cfg = dict(json.load(open(f"{BOT}/config.json"))); cfg["USE_BE_GUARD"] = False
    idx = np.mean([d["close"].values / d["close"].values[0] for d in frames.values()], axis=0)
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    tr = {s: np.where(d["close"].values > ema(d["close"].values, 48), 1, -1)
          for s, d in frames.items()}
    FEE = 0.001

    print("  " + "═" * 78)
    print(f"  {'설정':<28}{'봉인 앞90일(하락)':>25}{'개발 뒤90일(상승)':>25}")
    print("  " + "─" * 78)
    for nm, timeout in (("45분 횡보청산 ON (실거래 현황)", True),
                        ("45분 횡보청산 OFF (검증 모델)", False)):
        cells = []
        for lo, hi in ((0, mid), (mid, n0)):
            tot = wins = 0; pnl = 0.0
            for s, df in frames.items():
                sg = [x for x in sigs[s] if lo <= x["i"] < hi
                      and (tr[s][x["i"] - 1] > 0) == (x["dir"] == "long")]
                if not sg:
                    continue
                r = simulate_with_timeout(sg, df, cfg, timeout)
                tot += len(r); wins += sum(1 for x in r if x > 0)
                pnl += sum(r) - FEE * len(r)
            cells.append(f"{tot}건 {100*wins/tot if tot else 0:.0f}% {pnl*100:+.1f}%")
        print(f"  {nm:<28}{cells[0]:>25}{cells[1]:>25}")
    print("  " + "─" * 78)
    print("  판정: 두 구간 모두 OFF가 나아야 '제거가 옳다'고 말할 수 있다.")


if __name__ == "__main__":
    main()
