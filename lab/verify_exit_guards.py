#!/usr/bin/env python3
"""verify_exit_guards.py — 남은 청산 개입 장치 3종 검증

점검 대상 (2026-08-12 전수조사에서 발견)
────────────────────────────────────────
① 긴급 트레일링 `_check_emergency_trailing`  — 설정 스위치가 없어 **항상 ON**
     TP의 85%(`EMERGENCY_TS_THRESHOLD_RATIO`) 도달 시
       · 거래소 TP를 3배 멀리 밀고(승리를 더 끌게 함)
       · 대신 샹들리에 K를 3.0 → **0.8**로, 콜백을 0.8×ATR로 **좁힌다**
     TP는 멀어지지만 스톱이 4배 가까워지므로, 실제로는 그 부근에서 끊기기 쉽다.
     실측: DATA 숏 TP +1.00% · 최고 +1.02% · 청산 **+0.85%**(= TP×0.85).

② 고수익 가드 `USE_HIGH_ROI_TP_GUARD` (0.30)
     ROI +30% 도달 시 즉시 익절. 레버 환산 시 8401·8403은 가격 6%,
     8408·8409는 2.7%에서 강제 종료 — 큰 승리를 원천 차단한다.

③ 연속손절 한도 `MAX_CONSEC_SL_PER_DAY` (8403·8408·8409=3 / 8401=999)
     하루 3연속 손절이면 그날 매매 중단. 봇이 스스로 조건을 바꾸는 행위이고
     표본 확보에도 해롭다. 8401만 값이 달라 4봇 비교가 성립하지 않는다.

셋 다 어제 제거한 3종(본전보호·45분 횡보청산·분할익절)과 같은 계열이다.
같은 기준으로 판정한다 — 국면이 정반대인 두 구간 **모두** 개선되어야 채택.
"""
import json, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/l/project/8888")
exec(open("/Users/l/project/8888/lab/verify_gate_design.py").read()
     .split("def main():")[0].replace('if __name__', '#'))

FEE = 0.001
MAX_POS = 3
LEV = 5                     # 8403 기준(고수익 가드는 ROI라 레버리지가 필요)


def run_trade(df, s, direction, cfg, emg, roi_guard):
    """실거래 청산 경로 재현.

    emg       : 긴급 트레일링 사용 여부(TP×0.85 도달 시 K 3.0→0.8)
    roi_guard : 고수익 가드 사용 여부(ROI +30% = 가격 30/LEV% 도달 시 즉시 익절)
    """
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    k_base = g("CHANDELIER_K", 3.0)
    hold = int(g("MAX_HOLDING_HOURS", 6.0) * 4) or 10 ** 9
    emg_ratio = g("EMERGENCY_TS_THRESHOLD_RATIO", 0.85)
    roi_pct = g("HIGH_ROI_TP_GUARD_PCT", 0.30) / LEV      # ROI → 가격 변동률

    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = direction == "long"
    tp_pct = risk * rr
    sl = e * (1 - risk) if long else e * (1 + risk)
    peak = e
    k_cur = k_base
    armed = False            # 긴급 트레일링 전환 여부
    end = min(n - 1, i + hold)
    j, done, out = i, False, 0.0
    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e) / e if long else (e - lo) / e

        # 손절 우선(보수적)
        if (long and lo <= sl) or (not long and hi >= sl):
            out = (sl - e) / e if long else (e - sl) / e
            done = True
            break

        # ② 고수익 가드 — ROI 임계 도달 시 즉시 익절
        if roi_guard and gain >= roi_pct:
            out = roi_pct
            done = True
            break

        # ① 긴급 트레일링 — TP×0.85 도달 시 K 축소(TP는 3배로 밀려 사실상 무효)
        if emg and not armed and gain >= tp_pct * emg_ratio:
            armed = True
            k_cur = 0.8
            peak = hi if long else lo

        # 거래소 TP — 긴급 전환 전에만 유효(전환 시 3배 멀리 밀림)
        if not armed and gain >= tp_pct:
            out = tp_pct
            done = True
            break

        # 샹들리에 트레일링
        peak = max(peak, hi) if long else min(peak, lo)
        a = atr[j] if atr[j] == atr[j] else 0.0
        ch = (peak - k_cur * a) if long else (peak + k_cur * a)
        sl = max(sl, ch) if long else min(sl, ch)
        j += 1
    if not done:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), out - FEE


def simulate(frames, sigs, gates, cfg, lo, hi, emg, roi_guard, sl_cap):
    """sl_cap: 하루 연속손절 한도(None=무제한). 도달하면 그날 남은 진입을 막는다."""
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    busy, openp, pnl = {}, [], []
    streak, cur_day, halted = 0, None, False
    BARS_PER_DAY = 96                      # 15분봉
    for i, sym, s in allsig:
        day = i // BARS_PER_DAY
        if day != cur_day:
            cur_day, streak, halted = day, 0, False
        openp = [x for x in openp if x > i]
        if halted or busy.get(sym, -1) >= i or len(openp) >= MAX_POS:
            continue
        d = s["dir"]
        if (gates[sym][i - 1] > 0) != (d == "long"):
            continue
        ei, p = run_trade(frames[sym], s, d, cfg, emg, roi_guard)
        pnl.append(p); busy[sym] = ei; openp.append(ei)
        if sl_cap:
            streak = streak + 1 if p <= 0 else 0
            if streak >= sl_cap:
                halted = True
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
        ("현행 (긴급TS·ROI가드·손절한도3)", True,  True,  3),
        ("① 긴급 트레일링 해제",            False, True,  3),
        ("② 고수익 가드 해제",              True,  False, 3),
        ("③ 연속손절 한도 해제",            True,  True,  None),
        ("①+②+③ 셋 다 해제",              False, False, None),
    ]
    for nm, emg, roi, cap in variants:
        cells, nets = [], []
        for a, b in ((0, mid), (mid, n0)):
            p = simulate(frames, sigs, gates, cfg, a, b, emg, roi, cap)
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
