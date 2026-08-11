#!/usr/bin/env python3
"""verify_auto_switch.py — 자동 방향반전(USE_AUTO_MODE_SWITCH)의 실제 효과 검증

경위
────
나는 "매매 방향이 평균 3.75일마다 뒤집혔고, 이게 '4~5일 뒤 악화'의 정체"라고
말했다. mooja가 인과가 거꾸로라고 지적했고, 확인해 보니 그 지적이 옳았다.
반전의 방아쇠는 성적이다(engine.check_auto_mode_switch):

    * 청산 3~4건 시점: 3건 이상 손실이면 반전
    * 청산 5건 이상:   **최근 5건 중 3건 이상 손실**이면 반전

즉 반전은 나빠진 뒤에 일어나는 **결과**이지 원인이 아니다.
그런데도 나는 검증 없이 이 기능을 껐다. 그래서 여기서 근거를 만든다.

방법
────
어제 게이트를 판정한 방식 그대로. 진입 신호는 고정하고 자동반전만 켰다 껐다 하며
국면이 정반대인 두 구간에서 비교한다. 한쪽에서만 좋으면 국면 의존이므로 기각한다.

실거래 순서를 지킨다: 반전 판정은 **청산 시각** 기준으로 갱신되고,
그 이후 **진입**부터 방향이 바뀐다. 동시보유는 실거래와 같이 3개로 제한한다.
"""
import json, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/l/project/8888")
exec(open("/Users/l/project/8888/lab/verify_gate_design.py").read()
     .split("def main():")[0].replace('if __name__', '#'))

FEE = 0.001
MAX_POS = 3


def run_trade(df, s, direction, cfg):
    """한 건을 청산까지 굴려 (청산봉, 손익)을 돌려준다. 청산 경로는 실거래와 동일."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    pt_on = bool(cfg.get("USE_PARTIAL_TP", True))
    pt_trig, pt_frac = g("PARTIAL_TP_TRIGGER_PCT", .015), g("PARTIAL_TP_FRACTION", .5)
    k_ch = g("CHANDELIER_K", 3.0)
    hold = int(g("MAX_HOLDING_HOURS", 6.0) * 4) or 10 ** 9

    i, e, risk, rr = s["i"], s["e"], s["risk"], s["rr"]
    long = direction == "long"
    sl = e * (1 - risk) if long else e * (1 + risk)
    tp = e * (1 + risk * rr) if long else e * (1 - risk * rr)
    realized, remain = 0.0, 1.0
    part, trail, peak = False, False, e
    end = min(n - 1, i + hold)
    j, done = i, False
    while j <= end:
        hi, lo = h[j], l[j]
        gain = (hi - e) / e if long else (e - lo) / e
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
        j += 1
    if not done:
        last = c[min(j, end)]
        realized += remain * ((last - e) / e if long else (e - last) / e)
    return min(j, end), realized - FEE


def simulate(frames, sigs, gates, cfg, lo, hi, auto_switch):
    """진입 시각순으로 굴리며 자동반전 상태를 청산 시각 기준으로 갱신한다."""
    allsig = sorted(((x["i"], sym, x) for sym, v in sigs.items() for x in v
                     if lo <= x["i"] < hi), key=lambda t: t[0])
    pending = []          # (청산봉, 손익) — 아직 청산 시각이 안 된 것
    streak = []           # 연패 판정용. 전환 때 비운다(중복 전환 방지)
    all_pnl = []          # 손익 전체 기록. 절대 비우지 않는다
    busy_until = {}       # 심볼별 보유 종료봉
    open_pos = []         # 동시보유 추적(청산봉 목록)
    bluefrog = False

    for i, sym, s in allsig:
        # 1) 이 시점까지 청산된 거래를 연패 판정에 반영
        ready = [p for p in pending if p[0] <= i]
        if ready:
            ready.sort()
            for _, pnl in ready:
                all_pnl.append(pnl)
                streak.append(pnl)
                if auto_switch:
                    n = len(streak)
                    if n >= 5:
                        if sum(1 for x in streak[-5:] if x <= 0) >= 3:
                            bluefrog = not bluefrog
                            streak = []
                    elif n >= 3:
                        if sum(1 for x in streak if x <= 0) >= 3:
                            bluefrog = not bluefrog
                            streak = []
            pending = [p for p in pending if p[0] > i]
        open_pos = [x for x in open_pos if x > i]

        if busy_until.get(sym, -1) >= i or len(open_pos) >= MAX_POS:
            continue

        # 2) 역매매 반전 → 그 다음 게이트 (실거래 trader.on_signal 순서와 동일)
        d = s["dir"]
        if bluefrog:
            d = "short" if d == "long" else "long"
        if (gates[sym][i - 1] > 0) != (d == "long"):
            continue

        exit_i, pnl = run_trade(frames[sym], s, d, cfg)
        pending.append((exit_i, pnl))
        busy_until[sym] = exit_i
        open_pos.append(exit_i)

    all_pnl += [p for _, p in pending]      # 구간 끝까지 안 닫힌 건도 포함
    return all_pnl


def main():
    frames = load()
    n0 = len(next(iter(frames.values()))); mid = n0 // 2
    sigs = get_signals(frames)
    cfg = dict(json.load(open(f"{BOT}/config.json")))
    cfg["USE_BE_GUARD"] = False
    ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values
    gates = {s: np.where(d["close"].values > ema(d["close"].values, 48), 1, -1)
             for s, d in frames.items()}

    print("  " + "═" * 78)
    print(f"  {'설정':<30}{'봉인 앞90일(하락)':>24}{'개발 뒤90일(상승)':>24}")
    print("  " + "─" * 78)
    res = {}
    for nm, sw in (("자동반전 ON (원래 운영방식)", True),
                   ("자동반전 OFF (현재 4봇)", False)):
        cells = []
        for tag, a, b in (("봉인", 0, mid), ("개발", mid, n0)):
            p = simulate(frames, sigs, gates, cfg, a, b, sw)
            net = sum(p) * 100
            wr = 100 * sum(1 for x in p if x > 0) / len(p) if p else 0
            res[(nm, tag)] = net
            cells.append(f"{len(p)}건 {wr:.0f}% {net:+.1f}%")
        print(f"  {nm:<30}{cells[0]:>24}{cells[1]:>24}")
    print("  " + "─" * 78)
    d1 = res[("자동반전 ON (원래 운영방식)", "봉인")] - res[("자동반전 OFF (현재 4봇)", "봉인")]
    d2 = res[("자동반전 ON (원래 운영방식)", "개발")] - res[("자동반전 OFF (현재 4봇)", "개발")]
    print(f"  ON−OFF 차이: 봉인 {d1:+.1f}%p · 개발 {d2:+.1f}%p")
    if d1 > 0 and d2 > 0:
        print("  → 두 구간 모두 ON이 우세. 자동반전을 되살리는 것이 옳다.")
    elif d1 < 0 and d2 < 0:
        print("  → 두 구간 모두 OFF가 우세. 끈 채로 두는 것이 옳다.")
    else:
        print("  → 구간마다 엇갈림 = 국면 의존. 어느 쪽도 근거 없음(판정 보류).")


if __name__ == "__main__":
    main()
