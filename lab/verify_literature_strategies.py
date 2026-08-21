#!/usr/bin/env python3
"""verify_literature_strategies.py — 문헌 지지 전략을 우리 자료로 검증

왜 일봉인가
──────────
웹 조사 결론: 크립토에서 수익이 확인된 것은 **느린** 신호뿐이다.
  · 시계열 모멘텀 28일 룩백·5일 보유 → Sharpe 1.51 (시장 0.84), 10년 검증
  · 이동평균 10일/40일 → 10년 walk-forward, 손실 연도 1회
  · *"BTC 인트라데이 추세추종은 수익 나는 것이 없다"* ← 우리 15분·1시간봉 전멸과 일치
그래서 4시간봉 자료를 일봉으로 합쳐 검증한다.

부가전략 — 문헌 평가에 따라 취사
  · 변동성 타겟팅: 가장 잘 지지됨 → 넣는다
  · ATR 손절: 리스크 모델에 포함 → 넣는다
  · 변동성 국면 필터: 10% 수준에서만 유의(취약) → 켜고/끄고 둘 다 잰다
  · 추세 게이트: 변동성 타겟팅과 **중복** → 이중계산 주의, 따로 잰다
  · 역매매 자동전환: 문헌 지지 없음 + 우리 검증도 무의미 → 제외

과적합 방어 (오늘 132조합에서 유의미 0개였던 교훈)
  1. **최종 확인 구간(최근 6개월)은 아예 건드리지 않는다** — 마지막에 한 번만 본다
  2. 앞/뒤 절반 양쪽 플러스 + 6분할 4칸 이상
  3. 통과 기준 **2σ** (오늘 통과한 것들은 전부 1σ 미만이었다)
"""
import glob, json, os, sys
import numpy as np, pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_4h_3y"
FEE, SLIP, MAX_POS = 0.001, 0.0002, 3
HOLDOUT_DAYS = 180        # 최근 6개월 — 최종 확인용, 탐색에 쓰지 않는다


def load_daily():
    """4시간봉 6개 = 1일."""
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/okx_4h_*.json")):
        s = os.path.basename(p).replace("okx_4h_", "").replace(".json", "")
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        n = len(df) // 6 * 6
        df = df.iloc[len(df) - n:].reset_index(drop=True)
        g = df.groupby(df.index // 6)
        d = pd.DataFrame({"ts": g["ts"].first(), "open": g["open"].first(),
                          "high": g["high"].max(), "low": g["low"].min(),
                          "close": g["close"].last(), "volume": g["volume"].sum()
                          }).reset_index(drop=True)
        c, h, l = d["close"], d["high"], d["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        d["_atr"] = tr.ewm(span=14, adjust=False).mean()
        d["_vol"] = c.pct_change().rolling(20).std()      # 변동성 타겟팅용
        out[s] = d
    n = min(len(v) for v in out.values())
    return {k: v.iloc[-n:].reset_index(drop=True) for k, v in out.items()}


# ── 전략: (일자 t, 방향) 목록. t까지의 자료만 쓴다 ──────────────────────
def tsmom(df, look=28, rebal=5, top_third=True):
    """시계열 모멘텀 — 룩백 수익률이 과거 분포 상위 1/3이면 롱, 하위 1/3이면 숏."""
    c = df["close"].values
    n = len(c)
    r = np.full(n, np.nan)
    r[look:] = (c[look:] - c[:-look]) / c[:-look]
    out = []
    for t in range(look + 60, n - 1, rebal):
        hist = r[look:t + 1]
        hist = hist[np.isfinite(hist)]
        if len(hist) < 60 or not np.isfinite(r[t]):
            continue
        if top_third:
            hi, lo = np.percentile(hist, 67), np.percentile(hist, 33)
            if r[t] >= hi:
                out.append((t, "long"))
            elif r[t] <= lo:
                out.append((t, "short"))
        else:
            out.append((t, "long" if r[t] > 0 else "short"))
    return out


def ma_cross(df, fast=10, slow=40):
    c = df["close"]
    f, s = c.rolling(fast).mean().values, c.rolling(slow).mean().values
    out = []
    for t in range(slow + 1, len(c) - 1):
        if not (np.isfinite(f[t]) and np.isfinite(s[t]) and np.isfinite(f[t - 1])):
            continue
        if f[t - 1] <= s[t - 1] and f[t] > s[t]:
            out.append((t, "long"))
        elif f[t - 1] >= s[t - 1] and f[t] < s[t]:
            out.append((t, "short"))
    return out


def xsmom(frames, look=28, rebal=5, top=5):
    syms = list(frames)
    n = len(next(iter(frames.values())))
    closes = np.array([frames[s]["close"].values for s in syms])
    out = {s: [] for s in syms}
    for t in range(look + 60, n - 1, rebal):
        base = closes[:, t - look]
        r = np.where(base > 0, (closes[:, t] - base) / np.where(base > 0, base, 1), np.nan)
        ok = np.where(np.isfinite(r))[0]
        if len(ok) < 2 * top:
            continue
        order = ok[np.argsort(r[ok])]
        for k in order[-top:]:
            out[syms[k]].append((t, "long"))
        for k in order[:top]:
            out[syms[k]].append((t, "short"))
    return out


# ── 청산 + 부가전략 ──────────────────────────────────────────────────────
def run_trade(df, t, direction, sl_atr, hold, vol_target=None, vol_regime=False):
    """진입 = 다음 일봉 시가. 반환 (청산일, 손익%, 규모배수).

    변동성 타겟팅: 목표변동성 ÷ 실현변동성 으로 규모를 조절한다(0.3~2.0배 제한).
    변동성 국면 필터: 실현변동성이 과거 75분위를 넘으면 진입하지 않는다.
    """
    o, h, l, c = (df["open"].values, df["high"].values,
                  df["low"].values, df["close"].values)
    atr, vol = df["_atr"].values, df["_vol"].values
    n = len(c)
    i = t + 1
    if i >= n:
        return i, None, 0.0
    v = vol[t]
    if vol_regime:
        hist = vol[max(0, t - 250):t + 1]
        hist = hist[np.isfinite(hist)]
        if len(hist) > 30 and np.isfinite(v) and v > np.percentile(hist, 75):
            return i, None, 0.0
    size = 1.0
    if vol_target is not None:
        if not np.isfinite(v) or v <= 0:
            return i, None, 0.0
        size = float(np.clip(vol_target / v, 0.3, 2.0))

    long = direction == "long"
    e = o[i] * (1 + SLIP) if long else o[i] * (1 - SLIP)
    a0 = atr[t]
    if not np.isfinite(a0) or a0 <= 0 or e <= 0:
        return i, None, 0.0
    risk = sl_atr * a0 / e
    if risk <= 0 or risk > 0.30:
        return i, None, 0.0
    sl = e * (1 - risk) if long else e * (1 + risk)
    end, j, out = min(n - 1, i + hold), i, None
    while j <= end:
        if (long and l[j] <= sl) or (not long and h[j] >= sl):
            out = (sl - e) / e if long else (e - sl) / e
            break
        j += 1
    if out is None:
        last = c[min(j, end)]
        out = (last - e) / e if long else (e - last) / e
    return min(j, end), (out - FEE - SLIP) * size, size


def sim(frames, sigmap, lo, hi, sl_atr, hold, vt=None, vr=False):
    allsig = sorted(((t, s, d) for s, v in sigmap.items() for t, d in v
                     if lo <= t < hi), key=lambda x: x[0])
    busy, openp, pnl = {}, [], []
    for t, sym, d in allsig:
        openp = [x for x in openp if x > t]
        if busy.get(sym, -1) >= t or len(openp) >= MAX_POS:
            continue
        ei, p, _ = run_trade(frames[sym], t, d, sl_atr, hold, vt, vr)
        if p is None:
            continue
        pnl.append(p)
        busy[sym] = ei
        openp.append(ei)
    return pnl


def stat(p):
    if len(p) < 30:
        return None
    a = np.array(p) * 100
    return {"n": len(a), "sum": a.sum(), "mean": a.mean(),
            "se": a.std(ddof=1) / np.sqrt(len(a)), "win": 100 * (a > 0).mean(),
            "sigma": a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))}


def fmt(s):
    if s is None:
        return "표본부족"
    return f"{s['n']:>4}건 승{s['win']:>2.0f}% {s['mean']:+.3f}±{s['se']:.3f}({s['sigma']:+.1f}σ)"


def main():
    frames = load_daily()
    N = len(next(iter(frames.values())))
    search_end = N - HOLDOUT_DAYS          # 여기까지만 탐색에 쓴다
    mid = search_end // 2
    q = search_end // 6
    print(f"  {len(frames)}종목 · {N}일 (4시간봉 6개=1일)")
    print(f"  탐색 구간 0~{search_end}일 · **최종확인 구간 {search_end}~{N}일({HOLDOUT_DAYS}일)은 건드리지 않음**")

    strat = {
        "시계열모멘텀28": {s: tsmom(d, 28, 5) for s, d in frames.items()},
        "시계열모멘텀56": {s: tsmom(d, 56, 10) for s, d in frames.items()},
        "이동평균10/40": {s: ma_cross(d, 10, 40) for s, d in frames.items()},
        "이동평균20/100": {s: ma_cross(d, 20, 100) for s, d in frames.items()},
        "횡단면모멘텀28": xsmom(frames, 28, 5, 5),
    }
    ADDON = [("없음", None, False),
             ("변동성타겟팅", 0.04, False),
             ("변동성국면필터", None, True),
             ("둘 다", 0.04, True)]

    print("\n  " + "═" * 104)
    print(f"  {'전략':<15}{'부가':<14}{'손절':>5}{'보유':>5}"
          f"{'앞절반':>32}{'뒤절반':>32}{'6분할':>7}")
    print("  " + "─" * 104)
    keep = []
    for name, sm in strat.items():
        tot = sum(len(v) for v in sm.values())
        if tot < 200:
            print(f"  {name:<15} 신호 {tot}건 — 부족")
            continue
        for addon, vt, vr in ADDON:
            for sl_atr in (2.0, 3.0):
                for hold in (5, 20):
                    a = stat(sim(frames, sm, 0, mid, sl_atr, hold, vt, vr))
                    b = stat(sim(frames, sm, mid, search_end, sl_atr, hold, vt, vr))
                    if not (a and b and a["mean"] > 0 and b["mean"] > 0):
                        continue
                    wins = sum(1 for k in range(6)
                               if (lambda c: c and c["mean"] > 0)(
                                   stat(sim(frames, sm, k * q, (k + 1) * q,
                                            sl_atr, hold, vt, vr))))
                    two_sigma = a["sigma"] >= 2 and b["sigma"] >= 2
                    mark = "  ★★2σ통과" if (two_sigma and wins >= 4) else ("  ★" if wins >= 4 else "")
                    print(f"  {name:<15}{addon:<14}{sl_atr:>5.1f}{hold:>5}"
                          f"{fmt(a):>32}{fmt(b):>32}{wins:>5}/6{mark}", flush=True)
                    if two_sigma and wins >= 4:
                        keep.append((name, addon, sl_atr, hold, a, b, wins, sm, vt, vr))
    print("  " + "─" * 104)

    print("\n  ■ 2σ + 6분할 4칸 통과 → 최종확인 구간(최근 6개월) 검사")
    if not keep:
        print("    통과 없음 — 최종확인 생략")
        return
    for name, addon, sl_atr, hold, a, b, w, sm, vt, vr in keep:
        h = stat(sim(frames, sm, search_end, N, sl_atr, hold, vt, vr))
        ok = h and h["mean"] > 0
        print(f"    {name:<15}{addon:<14}손절{sl_atr:.1f} 보유{hold}일  "
              f"최종확인 {fmt(h)}  {'✅ 채택' if ok else '❌ 최종확인 실패'}")


if __name__ == "__main__":
    main()
