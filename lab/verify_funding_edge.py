#!/usr/bin/env python3
"""verify_funding_edge.py — 펀딩비 극단에 구조적 엣지가 있는가

가설
────
무기한 선물에서 롱이 몰리면 롱이 숏에게 8시간마다 펀딩비를 낸다. 이건 예측이 아니라
계약 조건이다. 펀딩비가 극단으로 치우쳤다는 건 **한쪽이 비용을 감수하면서까지 몰려
있다**는 뜻이고, 그런 포지션은 청산에 취약하다. 따라서 몰린 반대편에 서면 되돌림을
받을 수 있다 — 이것이 가격 패턴이 아닌 구조에서 나오는 엣지다.

**강건성 시험을 처음부터 함께 돌린다.** 캐스케이드 검증에서 헤드라인 숫자(t=2.6)를
먼저 보고 나서 때렸더니 기간 4분할·종목 분산에서 무너졌다. 소수 종목·소수 기간이
전부를 만드는 게 가짜 엣지의 전형이고, 그건 마지막이 아니라 처음에 봐야 한다.

채택 조건 (하나라도 미달이면 기각)
  · 왕복 0.2% 차감 후 양수 & t > 2
  · 기간 4분할에서 4구간 모두 양수
  · 기여 상위 5종목을 빼도 t > 2
"""
import glob, json, os
from collections import defaultdict
import numpy as np, pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_live"
FUND = "/Users/l/project/8888/lab_funding_hist"


def load():
    px, fd = {}, {}
    for p in sorted(glob.glob(f"{CACHE}/okx_15m_*.json")):
        s = os.path.basename(p).replace("okx_15m_", "").replace(".json", "")
        fp = os.path.join(FUND, f"{s}.json")
        if not os.path.exists(fp):
            continue
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        rows = sorted(set(map(tuple, json.load(open(fp)))))
        if len(rows) < 100:
            continue
        px[s] = df
        fd[s] = rows
    n = min(len(d) for d in px.values())
    px = {k: v.iloc[-n:].reset_index(drop=True) for k, v in px.items()}
    return px, fd


def events(px, fd, q, hold_bars):
    """펀딩 극단 이벤트 → (봉인덱스, 종목, 수익률).

    펀딩 정산 시각 직후 봉의 시가에 진입한다(정산 시점은 공개 정보라 앞당겨 쓸 수 없다).
    펀딩이 양(+)이면 롱이 비용을 낸다 = 롱 과밀 → 숏.
    """
    out = []
    for s, df in px.items():
        ts = df["ts"].values.astype("int64")
        o, c = df["open"].values, df["close"].values
        n = len(c)
        rows = fd[s]
        rates = np.array([r[1] for r in rows], dtype=float)
        # 종목별 분포로 극단 판정 (종목마다 펀딩 수준이 다르다)
        hi_thr = np.quantile(rates, 1 - q)
        lo_thr = np.quantile(rates, q)
        for t_ms, r in rows:
            if lo_thr < r < hi_thr:
                continue
            j = int(np.searchsorted(ts, t_ms, side="right"))   # 정산 직후 봉
            if j < 1 or j + hold_bars >= n:
                continue
            ent = o[j]
            if ent <= 0:
                continue
            sign = -1 if r > 0 else +1        # 롱 과밀이면 숏
            ex = c[j + hold_bars]
            out.append((j, s, sign * (ex - ent) / ent))
    return out


def stat(vals, fee=0.002):
    a = np.array(vals, dtype=float) - fee
    if len(a) < 30:
        return f"{len(a):>5}건  표본부족", 0.0, 0.0
    m = a.mean() * 100
    se = a.std(ddof=1) / np.sqrt(len(a)) * 100
    t = m / se if se > 0 else 0.0
    return f"{len(a):>5}건  {m:+.3f}%  (±{se:.3f} · t={t:+.1f})  {'✅' if m > 0 and t > 2 else '❌'}", m, t


def main():
    px, fd = load()
    n0 = len(next(iter(px.values())))
    print(f"  {len(px)}종목 · {n0}봉 = {n0*15/60/24:.0f}일 · 펀딩 이력 "
          f"{sum(len(v) for v in fd.values()):,}건")
    print("  진입: 펀딩 정산 직후 봉 시가 · 비용 왕복 0.2% · 펀딩 양수면 숏")

    best = None
    print("\n  ══ 격자 탐색 (극단 분위 × 보유시간) ══")
    print(f"  {'분위':<8}{'보유':<10}{'결과':<44}")
    for q in (0.05, 0.10, 0.20):
        for hold_h, hb in ((8, 32), (24, 96), (72, 288)):
            ev = events(px, fd, q, hb)
            line, m, t = stat([x[2] for x in ev])
            print(f"  상하 {q*100:>2.0f}%  {hold_h:>3}시간   {line}")
            if m > 0 and t > 2 and (best is None or t > best[0]):
                best = (t, q, hb, hold_h, ev)

    if best is None:
        print("\n  ══ 판정: 기각 ══")
        print("   왕복 0.2% 차감 후 t>2를 넘는 조합이 없다. 강건성 시험으로 갈 것도 없다.")
        return

    t, q, hb, hold_h, ev = best
    print(f"\n  ══ 최선 조합: 상하 {q*100:.0f}% · {hold_h}시간 (t={t:+.1f}) — 강건성 시험 ══")

    print("\n  1. 기간 4분할 (4구간 모두 양수여야 채택)")
    step = n0 // 4
    oks = 0
    for k in range(4):
        sub = [x[2] for x in ev if k * step <= x[0] < (k + 1) * step]
        line, m, _ = stat(sub)
        oks += m > 0
        print(f"     {k*45:>3}~{(k+1)*45:>3}일   {line}")

    print("\n  2. 종목 분산 (상위 5종목 제외 후 t>2여야 채택)")
    bysym = defaultdict(list)
    for _, s, v in ev:
        bysym[s].append(v)
    tot = {s: sum(v) for s, v in bysym.items()}
    top = sorted(tot, key=tot.get, reverse=True)[:5]
    print(f"     기여 상위 5: {', '.join(top)}")
    line, m2, t2 = stat([v for _, s, v in ev if s not in top])
    print(f"     상위5 제외   {line}")
    pos = sum(1 for s, v in bysym.items() if np.mean(v) - 0.002 > 0)
    print(f"     종목별 양수  {pos}/{len(bysym)} = {100*pos/len(bysym):.0f}%")

    print("\n  3. 비용 민감도")
    for fee in (0.001, 0.002, 0.003):
        line, _, _ = stat([x[2] for x in ev], fee)
        print(f"     왕복 {fee*100:.1f}%    {line}")

    print("\n  ══ 판정 ══")
    ok = (oks == 4) and (m2 > 0 and t2 > 2)
    print(f"   기간 4구간 모두 양수: {'예' if oks == 4 else f'아니오 ({oks}/4)'}")
    print(f"   상위5 제외 후 t>2  : {'예' if (m2 > 0 and t2 > 2) else '아니오'}")
    print(f"   → {'채택 후보 — 추가 검증 필요' if ok else '기각'}")


if __name__ == "__main__":
    main()
