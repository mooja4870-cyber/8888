#!/usr/bin/env python3
"""verify_ensemble_trend.py — 추세추종 3종과 '합의 방식'을 우리 자료로 검증

경위
────
mooja 지시로 8409에 넣을 추세추종 전략을 웹 조사했고, 3개 후보와 '합의 방식'이 나왔다.
조사에서 반복된 결론은 **어떤 시스템도 단독으로 이기지 않는다**는 것이었고,
가장 방어 가능한 방식으로 **세 지표가 동시에 같은 방향일 때만 진입**이 제시됐다.

웹 수치는 종목·기간·비용이 제각각이라 그대로 쓸 수 없다.
  · 터틀:     8코인 1년 +18.59%, 승률 35.94%
  · 켈트너:   크립토 수치 거의 없음
  · 슈퍼트렌드: BTC 8.6년 CAGR 33%인데 **단순보유(37.6%)에 졌다**
같은 종목·같은 기간·같은 비용으로 다시 잰다.

세 시스템 (조사에서 권고된 '느린 설정' 채택)
  1 터틀시스템2  55일 최고가 돌파 → 롱 / 20일 최저가 이탈 → 청산
  2 켈트너      EMA20 ± ATR×2 상단 돌파 → 롱 / 중심선 이탈 → 청산
  3 슈퍼트렌드   ATR(10)×3.0 추적선 위 → 롱

합의 = 셋의 방향 상태가 모두 일치하는 첫 봉에 진입.

조사에서 반복된 권고 3가지도 함께 시험한다
  · **롱 전용** — 크립토 추세시스템에서 숏이 수익을 갉아먹는다는 지적이 여러 곳
  · 느린 설정 — 55일 > 20일
  · 여유 있는 손절 — ATR 배수를 넉넉히

판정 기준 (8403 때와 동일)
  · 앞절반/뒤절반 양쪽 건당 플러스
  · 6분할 4칸 이상
  · **최근 180일은 탐색에서 제외**, 통과한 것만 마지막에 한 번 본다
"""
import sys
import numpy as np, pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_ma_expanded import (load_daily_aligned, run_trade, trades, stat, acct,
                                HOLDOUT_DAYS, MAX_POS)


# ── 세 시스템의 방향 상태 (+1 롱 / −1 숏 / 0 없음) ──────────────────────
def state_turtle(df, n_in=55, n_out=20):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    hh = pd.Series(h).rolling(n_in).max().shift(1).values
    ll = pd.Series(l).rolling(n_in).min().shift(1).values
    xh = pd.Series(h).rolling(n_out).max().shift(1).values
    xl = pd.Series(l).rolling(n_out).min().shift(1).values
    st = np.zeros(len(c))
    cur = 0
    for t in range(len(c)):
        if not np.isfinite(hh[t]) or not np.isfinite(c[t]):
            st[t] = 0
            continue
        if cur == 0:
            if c[t] > hh[t]:
                cur = 1
            elif c[t] < ll[t]:
                cur = -1
        elif cur == 1 and np.isfinite(xl[t]) and c[t] < xl[t]:
            cur = 0
        elif cur == -1 and np.isfinite(xh[t]) and c[t] > xh[t]:
            cur = 0
        st[t] = cur
    return st


def state_keltner(df, ema=20, mult=2.0):
    c = df["close"]
    m = c.ewm(span=ema, adjust=False).mean().values
    a = df["_atr"].values
    cv = c.values
    st = np.zeros(len(cv))
    cur = 0
    for t in range(len(cv)):
        if not (np.isfinite(m[t]) and np.isfinite(a[t]) and np.isfinite(cv[t])):
            st[t] = 0
            continue
        up, dn = m[t] + mult * a[t], m[t] - mult * a[t]
        if cur == 0:
            if cv[t] > up:
                cur = 1
            elif cv[t] < dn:
                cur = -1
        elif cur == 1 and cv[t] < m[t]:
            cur = 0
        elif cur == -1 and cv[t] > m[t]:
            cur = 0
        st[t] = cur
    return st


def state_supertrend(df, mult=3.0):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    a = df["_atr"].values
    n = len(c)
    st = np.zeros(n)
    cur, line = 0, np.nan
    for t in range(n):
        if not (np.isfinite(a[t]) and np.isfinite(c[t])):
            st[t] = 0
            continue
        hl2 = (h[t] + l[t]) / 2.0
        up, dn = hl2 + mult * a[t], hl2 - mult * a[t]
        if cur == 0 or not np.isfinite(line):
            cur, line = (1, dn) if c[t] > hl2 else (-1, up)
        elif cur == 1:
            line = max(line, dn)
            if c[t] < line:
                cur, line = -1, up
        else:
            line = min(line, up)
            if c[t] > line:
                cur, line = 1, dn
        st[t] = cur
    return st


def sig_from_states(states, mode, long_only):
    """상태 배열들 → (t, 방향). mode: 'turtle'|'keltner'|'super'|'consensus'"""
    okv = states["_ok"]
    if mode == "consensus":
        arrs = [states["turtle"], states["keltner"], states["super"]]
        agree = np.where((arrs[0] == arrs[1]) & (arrs[1] == arrs[2]), arrs[0], 0)
    else:
        agree = states[mode]
    out, prev = [], 0
    for t in range(1, len(agree) - 1):
        cur = agree[t]
        if cur != 0 and cur != prev and okv[t]:
            if long_only and cur < 0:
                prev = cur
                continue
            out.append((t, "long" if cur > 0 else "short"))
        prev = cur
    return out


def fmt(s):
    if s is None:
        return "표본부족"
    return f"{s['n']:>4}건 승{s['win']:>2.0f}% {s['mean']:+.2f}±{s['se']:.2f}({s['sigma']:+.1f}σ)"


def main():
    frames, N = load_daily_aligned()
    SE = N - HOLDOUT_DAYS
    q = SE // 6
    print(f"  {len(frames)}종목 · {N}일 · 탐색 0~{SE}일 · **최종확인 {SE}~{N}일 미사용**")
    print("  진입=다음 봉 시가 · 수수료 0.1% + 미끄러짐 0.02%×2")

    print("\n  상태 계산 중...", flush=True)
    ST = {}
    for s, d in frames.items():
        ST[s] = {"turtle": state_turtle(d), "keltner": state_keltner(d),
                 "super": state_supertrend(d), "_ok": d["_ok"].values}

    print("  " + "═" * 92)
    print(f"  {'전략':<16}{'방향':<8}{'손절':>5}{'보유':>5}"
          f"{'앞절반':>27}{'뒤절반':>27}{'6분할':>7}")
    print("  " + "─" * 92)
    keep = []
    for mode, label in (("turtle", "터틀55/20"), ("keltner", "켈트너"),
                        ("super", "슈퍼트렌드"), ("consensus", "★합의(3개)")):
        for long_only in (True, False):
            sm = {s: sig_from_states(ST[s], mode, long_only) for s in frames}
            tot = sum(len(v) for v in sm.values())
            if tot < 100:
                print(f"  {label:<16}{'롱전용' if long_only else '롱숏':<8} 신호 {tot}건 — 부족")
                continue
            for sl_atr in (3.0, 5.0):
                for hold in (30, 60):
                    a = stat(trades(frames, sm, 0, SE // 2, sl_atr, hold))
                    b = stat(trades(frames, sm, SE // 2, SE, sl_atr, hold))
                    if not (a and b and a["mean"] > 0 and b["mean"] > 0):
                        continue
                    wins = sum(1 for k in range(6)
                               if (lambda c: c and c["mean"] > 0)(
                                   stat(trades(frames, sm, k * q, (k + 1) * q, sl_atr, hold))))
                    two = a["sigma"] >= 2 and b["sigma"] >= 2
                    mark = "  ★★2σ" if (two and wins >= 4) else ("  ★" if wins >= 4 else "")
                    print(f"  {label:<16}{'롱전용' if long_only else '롱숏':<8}"
                          f"{sl_atr:>5.1f}{hold:>5}{fmt(a):>27}{fmt(b):>27}{wins:>5}/6{mark}",
                          flush=True)
                    if wins >= 4:
                        keep.append((label, long_only, sl_atr, hold, a, b, wins, sm))
    print("  " + "─" * 92)

    print("\n  ■ 6분할 4칸 이상 통과 → 최종확인 구간(최근 180일)")
    if not keep:
        print("    통과 없음")
        return
    for label, lo, sl_atr, hold, a, b, w, sm in keep:
        tr = trades(frames, sm, SE, N, sl_atr, hold)
        h = stat(tr)
        ac = acct(tr, HOLDOUT_DAYS, 0.10)
        ok = h and h["mean"] > 0
        extra = f" · 월 {ac['mret']:+.1f}% · 낙폭 {ac['mdd']:.1f}%" if ac else ""
        print(f"    {label:<16}{'롱전용' if lo else '롱숏':<8}손절{sl_atr:.1f} 보유{hold}일  "
              f"{fmt(h)}{extra}  {'✅' if ok else '❌'}")


if __name__ == "__main__":
    main()
