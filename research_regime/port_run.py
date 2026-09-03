"""포트폴리오 재검증 실행 — 손절 격자 × 기간(전체/최근2년) × 무작위 널 200회."""
import numpy as np, pandas as pd
import port as P
import warnings; warnings.filterwarnings("ignore")

STOPS = [None, 0.08, 0.05, 0.03]
NULL_N = 200


def fmt(s):
    return "%+7.1f%% %+6.1f%%/y  MDD %6.1f%%  Sharpe %5.2f" % (
        s["ret"] * 100, s["cagr"] * 100, s["mdd"] * 100, s["sharpe"])


def section(cal, D, start, label):
    print("=" * 96)
    print("%s   (%s ~ %s)" % (label, str(cal[0] if start is None else start)[:10], str(cal[-1])[:10]))
    print("=" * 96)

    bh = P.buyhold(cal, D, start=start)
    sb = P.stats(bh)
    print("  %-14s %s" % ("균등보유(베타)", fmt(sb)))
    print("  %-14s %s" % ("", "기간4분할 " + " ".join("%+6.1f%%" % (q * 100) for q in P.quarters(bh))))
    print()

    print("  %-10s %-52s %-30s" % ("손절", "전략", "기간4분할"))
    best = None
    results = {}
    for stop in STOPS:
        cur, tr = P.simulate(cal, D, stop_pct=stop, start=start)
        s = P.stats(cur)
        qs = P.quarters(cur)
        tag = "없음" if stop is None else "%.0f%%" % (stop * 100)
        print("  %-10s %-52s %s   거래 %d건" % (
            tag, fmt(s), " ".join("%+6.1f%%" % (q * 100) for q in qs), len(tr)))
        results[stop] = (cur, tr, s, qs)
        if best is None or s["cagr"] > results[best][2]["cagr"]:
            best = stop
    print()

    # ── 최고 조합의 국면별 분해 ──
    cur, tr, s, qs = results[best]
    tag = "없음" if best is None else "%.0f%%" % (best * 100)
    print("  ── 최고 조합(손절 %s) 국면별 분해 ──" % tag)
    if not tr.empty:
        for rg in ("BULL", "BEAR", "RANGE"):
            g = tr[tr["regime"] == rg]
            if g.empty:
                print("    %-6s 거래 없음" % rg); continue
            wr = (g["pnl"] > 0).mean() * 100
            print("    %-6s 거래 %4d건  손익 %+9.0f  승률 %4.1f%%  건당 %+7.0fbp  "
                  "롱 %d/숏 %d" % (rg, len(g), g["pnl"].sum(), wr, g["ret_bp"].mean(),
                                   (g["dir"] == 1).sum(), (g["dir"] == -1).sum()))
        why = tr["why"].value_counts()
        print("    청산사유 " + " · ".join("%s %d" % (k, v) for k, v in why.items()))
    print()

    # ── 널 분포 3종 — 신호의 어느 부분에 값이 있는지 분해한다 ──
    print("  ── 널 분포 %d회 (손절 %s) ──" % (NULL_N, tag))
    i0 = 0 if start is None else int(np.searchsorted(cal, start))
    i1 = len(cal) - 1
    ent_days = np.searchsorted(cal, tr["entry_date"].values) if not tr.empty else np.array([])
    ent_dirs = tr["dir"].values.astype(int) if not tr.empty else np.array([])
    real = s["cagr"]

    def null_run(maker):
        out, cnt = [], []
        for k in range(NULL_N):
            rng = np.random.default_rng(1000 + k)
            c, t = maker(rng)
            v = P.stats(c)["cagr"]
            if np.isfinite(v):
                out.append(v); cnt.append(len(t))
        return np.array(out), (np.mean(cnt) if cnt else 0)

    def report(label, nulls, cnt, note):
        z = (real - nulls.mean()) / nulls.std() if nulls.std() > 0 else 0.0
        print("    %-22s 중앙값 %+6.1f%%/y (5~95%%: %+6.1f ~ %+6.1f) 평균 %4.0f건 "
              "→ z=%+.2f %s" % (label, np.median(nulls) * 100,
                                np.percentile(nulls, 5) * 100, np.percentile(nulls, 95) * 100,
                                cnt, z, "✅" if z >= 2 else "❌"))
        print("      %s" % note)

    n1, c1 = null_run(lambda r: P.simulate(cal, D, stop_pct=best, mode="random", rng=r, start=start))
    report("A 종목만 무작위", n1, c1, "날짜·건수·롱숏비율은 실제와 동일 → 차이는 '어느 종목을 골랐나'뿐")

    def sched_maker(r):
        sc = {}
        days = r.integers(i0, i1, size=len(ent_days))
        dd = ent_dirs.copy(); r.shuffle(dd)
        for d, x in zip(days, dd):
            sc.setdefault(int(d), []).append(int(x))
        return P.simulate(cal, D, stop_pct=best, mode="schedule", rng=r, start=start, schedule=sc)

    n2, c2 = null_run(sched_maker)
    report("B 날짜+종목 무작위", n2, c2, "총건수·롱숏비율만 보존 → 차이는 '언제·어느 종목'")

    creg, treg = P.simulate(cal, D, stop_pct=best, mode="regime_only", start=start)
    sreg = P.stats(creg)
    print("    %-22s %s  %d건" % ("C 국면방향만(신호X)", fmt(sreg), len(treg)))
    print("      Donchian을 완전히 빼고 BULL=롱·BEAR=숏만 매일 채운 것 "
          "→ 실제 %+.1f%%/y 와 비교" % (real * 100))
    print()

    # ── 사전 합격선 판정 ──
    ok_q = all(q > 0 for q in qs)
    ok_bh = s["cagr"] > sb["cagr"]
    ok_mdd = s["mdd"] > -0.50
    print("  ── 사전 합격선 ──")
    print("    기간 4분할 전부 양수 : %s" % ("✅" if ok_q else "❌ %s" % " ".join("%+.1f%%" % (q*100) for q in qs)))
    print("    균등보유 초과        : %s (전략 %+.1f%%/y vs 베타 %+.1f%%/y)" % (
        "✅" if ok_bh else "❌", s["cagr"] * 100, sb["cagr"] * 100))
    print("    최대낙폭 50%% 이내    : %s (%.1f%%)" % ("✅" if ok_mdd else "❌", s["mdd"] * 100))
    print()
    return results, sb


if __name__ == "__main__":
    cal, D = P.build()
    print("포트폴리오 재검증 — 8402 실제 제약 적용")
    print("  MAX_POSITIONS=%d · LEVERAGE=%d · EQUITY_SCALE=%.1f · 노출상한 $%.0f/건 · 비용 왕복 %.0fbp"
          % (P.MAX_POSITIONS, P.LEVERAGE, P.EQUITY_SCALE, P.MAX_NOTIONAL, P.COST_BP))
    print("  국면별 보유 " + " · ".join("%s %d일" % (k, v) for k, v in P.HOLD_BY_REGIME.items())
          + " · RANGE는 거래량 확인 추가\n")

    section(cal, D, None, "① 전체 기간")
    section(cal, D, pd.Timestamp("2024-09-04"), "② 최근 2년")
