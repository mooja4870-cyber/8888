"""시장국면 타이밍 오버레이 검정 — 블록 부트스트랩 널 200회."""
import numpy as np, pandas as pd
import timing as T
import warnings; warnings.filterwarnings("ignore")

NULL_N = 200
LEV = 1.5      # port.py와 같은 총노출 (EQUITY_SCALE 0.5 × LEVERAGE 3)


def line(lbl, s, extra=""):
    return "  %-26s %+8.1f%%/y  MDD %6.1f%%  Sharpe %5.2f %s" % (
        lbl, s["cagr"] * 100, s["mdd"] * 100, s["sharpe"], extra)


def run(cal, rets, reg, start, label):
    i0 = int(np.searchsorted(cal, start)) if start is not None else 0
    c, r, g = cal[i0:], rets[i0:], reg[i0:]
    print("=" * 100)
    print("%s   (%s ~ %s)  거래일 %d" % (label, str(c[0])[:10], str(c[-1])[:10], len(c)))
    print("=" * 100)

    bh = T.equity(r, np.ones(len(r), bool), LEV, LEV)
    sbh = T.stats(bh, c)
    print(line("항상보유(베타)", sbh, "기간4분할 " +
               " ".join("%+6.1f%%" % (q * 100) for q in T.quarters(bh))))

    out = {}
    for name, mask in (("BULL만 보유", T.tradable(g == "BULL")),
                       ("BULL 정상·그외 절반", T.tradable(g == "BULL"))):
        eo = 0.0 if name.endswith("보유") else LEV * 0.5
        e = T.equity(r, mask, LEV, eo)
        s = T.stats(e, c)
        tim = mask.mean() * 100
        print(line(name, s, "시장체류 %4.1f%%  기간4분할 %s" % (
            tim, " ".join("%+6.1f%%" % (q * 100) for q in T.quarters(e)))))
        out[name] = (e, s, mask, eo)
    print()

    # ── 블록 부트스트랩 널 ──
    print("  ── 널 %d회: 같은 개수·같은 길이의 구간을 무작위 위치에 다시 깖 ──" % NULL_N)
    for name, (e, s, mask, eo) in out.items():
        vals = []
        for k in range(NULL_N):
            rng = np.random.default_rng(500 + k)
            nm = T.null_masks(mask, rng)
            vals.append(T.stats(T.equity(r, nm, LEV, eo), c)["cagr"])
        v = np.array([x for x in vals if np.isfinite(x)])
        z = (s["cagr"] - v.mean()) / v.std() if v.std() > 0 else 0.0
        pct = (v < s["cagr"]).mean() * 100
        print("    %-22s 널 중앙값 %+7.1f%%/y (5~95%%: %+6.1f ~ %+6.1f)  "
              "실제 %+7.1f%%  상위%3.0f%%  z=%+.2f %s" % (
                  name, np.median(v) * 100, np.percentile(v, 5) * 100,
                  np.percentile(v, 95) * 100, s["cagr"] * 100, pct, z,
                  "✅ 유의" if z >= 2 else "❌"))
    print()

    # ── 낙폭 맞춘 단순보유 ──
    print("  ── 낙폭을 맞춘 단순보유와 견줌 (낙폭 개선은 노출만 줄여도 공짜로 얻는다) ──")
    for name, (e, s, mask, eo) in out.items():
        best = None
        for x in np.arange(0.05, 3.01, 0.05):
            b = T.stats(T.equity(r, np.ones(len(r), bool), x, x), c)
            if best is None or abs(b["mdd"] - s["mdd"]) < abs(best[1]["mdd"] - s["mdd"]):
                best = (x, b)
        x, b = best
        d = s["cagr"] - b["cagr"]
        print("    %-22s 전략 %+7.1f%%/y  vs  단순보유%.2fx %+7.1f%%/y (MDD %5.1f%%)  차이 %+6.1f%%p %s"
              % (name, s["cagr"] * 100, x, b["cagr"] * 100, b["mdd"] * 100, d * 100,
                 "✅" if d > 0 else "❌"))
    print()
    return out, sbh


if __name__ == "__main__":
    cal, rets = T.basket()
    for kind, nm in (("adx", "BTC ADX+200MA"), ("side", "BTC 200MA 위/아래")):
        mr = T.market_regime(kind)
        reg = np.array([mr.get(d, None) for d in cal], dtype=object)
        print("\n" + "#" * 100)
        print("# 시장국면 판정: %s   (숏 없음 — ⑤ 조건이 깨져 방향이 아니라 노출만 조절)" % nm)
        print("#" * 100)
        run(cal, rets, reg, None, "① 전체 기간")
        run(cal, rets, reg, pd.Timestamp("2024-09-04"), "② 최근 2년")
