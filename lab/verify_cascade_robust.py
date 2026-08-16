#!/usr/bin/env python3
"""verify_cascade_robust.py — 캐스케이드 되돌림을 깨보는 시험

verify_cascade_edge.py에서 ATR×3.0 · 거래량 상위 2% 이벤트가 양 구간 모두
수수료 차감 후 +0.28~0.42%(t=2.0~2.5)로 나왔다. 이번 주 처음으로 채택 기준을
통과한 결과다. 그래서 오히려 의심해야 한다. 무너지는지 네 가지로 때린다.

1. 체결 현실화 — 급락 봉 **종가**에 사는 건 불가능하다. 다음 봉 **시가**로 바꾼다.
2. 비용 현실화 — 캐스케이드 순간은 스프레드가 벌어진다. 왕복 0.1% / 0.2% / 0.3%.
3. 기간 분할 — 180일을 4구간으로 쪼갠다. 한 구간이 전부를 만든 것이면 가짜다.
4. 종목 분산 — 상위 5종목을 빼도 남는지. 한두 종목의 사건이면 가짜다.

하나라도 무너지면 채택하지 않는다.
"""
import glob, json, os
from collections import defaultdict
import numpy as np, pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_live"
VOL_WIN = 96
K_ATR, VOLQ = 3.0, 0.98
FWD = 8               # 2시간 — 두 구간 모두 t가 가장 높았던 구간


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
        df["_ret"] = c.pct_change()
        df["_volq"] = df["volume"].rolling(VOL_WIN).rank(pct=True)
        out[s] = df
    n = min(len(d) for d in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


def events(frames, entry_mode):
    """이벤트 목록 (봉인덱스, 종목, 되돌림 수익률). entry_mode: 'close' | 'next_open'"""
    out = []
    for s, df in frames.items():
        c = df["close"].values
        o = df["open"].values
        ret = df["_ret"].values
        atr = df["_atr"].values
        vq = df["_volq"].values
        n = len(c)
        thr = K_ATR * (atr / np.where(c == 0, np.nan, c))
        for i in range(VOL_WIN + 1, n - FWD - 2):
            if not np.isfinite(thr[i]) or thr[i] <= 0 or vq[i] < VOLQ:
                continue
            if ret[i] <= -thr[i]:
                sign = +1                      # 급락 → 롱(반등)
            elif ret[i] >= thr[i]:
                sign = -1                      # 급등 → 숏(하락)
            else:
                continue
            if entry_mode == "close":
                ent, ei = c[i], i
            else:
                ent, ei = o[i + 1], i + 1      # 다음 봉 시가에 체결
            if ent <= 0:
                continue
            ex = c[ei + FWD]
            out.append((i, s, sign * (ex - ent) / ent))
    return out


def stat(vals, fee):
    a = np.array(vals, dtype=float) - fee
    if len(a) < 30:
        return f"{len(a):>5}건  표본부족"
    m = a.mean() * 100
    se = a.std(ddof=1) / np.sqrt(len(a)) * 100
    t = m / se if se > 0 else 0
    return f"{len(a):>5}건  {m:+.3f}%  (±{se:.3f} · t={t:+.1f})  {'✅' if m > 0 and t > 2 else '❌'}"


def main():
    frames = load()
    n0 = len(next(iter(frames.values())))
    print(f"  {len(frames)}종목 · {n0}봉 = {n0*15/60/24:.0f}일")
    print(f"  이벤트: 1봉 수익률 > ATR×{K_ATR} & 거래량 상위 {(1-VOLQ)*100:.0f}% · 보유 {FWD}봉({FWD*15}분)")

    ev_close = events(frames, "close")
    ev_open = events(frames, "next_open")

    print("\n  ══ 1. 체결 현실화 (급락봉 종가 → 다음봉 시가) ══")
    for nm, ev in (("종가 체결(비현실)", ev_close), ("다음봉 시가 체결", ev_open)):
        print(f"   {nm:<20} {stat([x[2] for x in ev], 0.001)}")

    print("\n  ══ 2. 비용 현실화 (다음봉 시가 체결 기준) ══")
    for fee in (0.001, 0.002, 0.003):
        print(f"   왕복 {fee*100:.1f}%          {stat([x[2] for x in ev_open], fee)}")

    print("\n  ══ 3. 기간 4분할 (다음봉 시가 · 왕복 0.2%) ══")
    q = n0 // 4
    for k in range(4):
        lo, hi = k * q, (k + 1) * q
        sub = [x[2] for x in ev_open if lo <= x[0] < hi]
        print(f"   {k*45:>3}~{(k+1)*45:>3}일        {stat(sub, 0.002)}")

    print("\n  ══ 4. 종목 분산 (다음봉 시가 · 왕복 0.2%) ══")
    bysym = defaultdict(list)
    for _, s, v in ev_open:
        bysym[s].append(v)
    tot = {s: sum(v) for s, v in bysym.items()}
    top = sorted(tot, key=tot.get, reverse=True)[:5]
    print(f"   기여 상위 5종목: {', '.join(top)}")
    rest = [v for _, s, v in ev_open if s not in top]
    print(f"   상위5 제외        {stat(rest, 0.002)}")
    pos = sum(1 for s, v in bysym.items() if np.mean(v) - 0.002 > 0)
    print(f"   종목별 양수 비율   {pos}/{len(bysym)} = {100*pos/len(bysym):.0f}%")

    print("\n  ══ 판정 ══")
    a = np.array([x[2] for x in ev_open]) - 0.002
    m, se = a.mean() * 100, a.std(ddof=1) / np.sqrt(len(a)) * 100
    print(f"   현실적 가정(다음봉 시가·왕복 0.2%): {m:+.3f}% ± {se:.3f} (t={m/se:+.1f}), {len(a)}건")
    print(f"   180일 누적 기대: {m*len(a)/100:+.1f}% (포지션 1개 기준, 중복 미고려)")


if __name__ == "__main__":
    main()
