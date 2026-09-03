"""분류기 스코어보드 — 사전 합격선(clf.py 상단)에 따라 판정한다."""
import numpy as np, pandas as pd
import clf as C
import warnings; warnings.filterwarnings("ignore")


def score(df, name, h, rl):
    col, fc = name, f"f{h}"
    sub = df[df[col].notna() & df[fc].notna()]
    if sub.empty:
        return None
    g = sub.groupby(col)[fc]
    mu = g.mean().to_dict(); n = g.size().to_dict()
    bull, bear = mu.get("BULL", np.nan), mu.get("BEAR", np.nan)
    spread = bull - bear
    uncond = sub[fc].mean()

    def sp(x):
        m = x.groupby(col)[fc].mean()
        return m.get("BULL", np.nan) - m.get("BEAR", np.nan)

    def bearmu(x):
        return x.groupby(col)[fc].mean().get("BEAR", np.nan)

    sub = sub.copy()
    sub["q"] = pd.qcut(sub["date"].astype("int64"), 4, labels=list("1234"))
    qs = sub.groupby("q", observed=True).apply(sp)
    qbear = sub.groupby("q", observed=True).apply(bearmu)
    bysym = sub.groupby("sym").apply(sp).dropna()
    frac = (bysym > 0).mean() if len(bysym) else 0.0

    c1 = bool((qs > 0).all())
    c2 = frac >= C.MIN_SYM_FRAC
    c3 = min(n.get("BULL", 0), n.get("BEAR", 0)) >= C.MIN_N and rl >= C.MIN_RUN
    c4 = spread >= C.MIN_SPREAD
    c5 = (bear < 0) and int((qbear < 0).sum()) >= 3
    return dict(bull=bull, bear=bear, spread=spread, uncond=uncond, qs=qs.values,
                qbear=qbear.values, frac=frac, nbull=n.get("BULL", 0), nbear=n.get("BEAR", 0),
                rl=rl, c1=c1, c2=c2, c3=c3, c4=c4, c5=c5, ok=c1 and c2 and c3 and c4)


if __name__ == "__main__":
    df, rls = C.collect()
    print("국면 분류기 스코어보드 — 전략 없음, 비용 없음, 라벨의 예측력만")
    print("사전 합격선: ①4분할 전부 양수 ②종목 70%↑ ③표본1000·연속5일↑ ④분리력 30bp↑")
    print("             ⑤(숏 조건) BEAR 평균 음수 & 4분할 중 3분기↑ 음수\n")

    for h in C.HORIZONS:
        print("=" * 108)
        print("보유 %d일   (무조건 롱 평균 = 시장 드리프트)" % h)
        print("=" * 108)
        print("  %-22s %8s %8s %8s  %-26s %6s %7s %s" % (
            "분류기", "BULL", "BEAR", "분리력", "분리력 4분할", "종목%", "연속일", "판정"))
        rank = []
        for name, _ in C.CLFS:
            s = score(df, name, h, rls[name])
            if s is None:
                continue
            rank.append((s["spread"], name, s))
            flags = "".join(k for k, v in [("①", s["c1"]), ("②", s["c2"]),
                                           ("③", s["c3"]), ("④", s["c4"])] if not v)
            print("  %-22s %+8.0f %+8.0f %+8.0f  %-26s %5.0f%% %6.1f %s" % (
                name, s["bull"], s["bear"], s["spread"],
                " ".join("%+6.0f" % v for v in s["qs"]), s["frac"] * 100, s["rl"],
                "✅ 통과" if s["ok"] else "❌ " + flags))
        print()
        # 숏 가능 여부 — 이게 깨지면 국면은 크기 조절에만 쓸 수 있다
        print("  ── ⑤ 숏 사용 조건: BEAR 라벨의 미래수익이 실제로 음수인가 ──")
        for _, name, s in sorted(rank, reverse=True)[:5]:
            print("    %-22s BEAR %+7.0fbp  4분할 %s  %s" % (
                name, s["bear"], " ".join("%+6.0f" % v for v in s["qbear"]),
                "✅ 숏 가능" if s["c5"] else "❌ 숏 불가"))
        print()
