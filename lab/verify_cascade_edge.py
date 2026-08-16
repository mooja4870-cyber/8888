#!/usr/bin/env python3
"""verify_cascade_edge.py — 청산 캐스케이드 되돌림에 엣지가 있는가

왜 이걸 보는가
─────────────
가격 패턴 전략은 8전 8패였다. 패턴은 누구나 보고, 보이면 사라진다.
대신 **강제된 거래**를 찾는다. 청산은 자발적 매매가 아니다. 증거금이 모자라면
가격을 따지지 않고 시장가로 던져야 한다. 던지는 쪽은 반드시 손해를 감수한다.
그 손해가 누군가의 이익이고, 그건 경쟁으로 사라지지 않는 구조적 자리다.

캐스케이드 대용 지표 (청산 데이터가 없으므로 OHLCV로 근사)
  · 한 봉의 수익률이 ATR의 K배를 넘고
  · 그 봉의 거래량이 최근 96봉(24시간) 중 상위 Q분위
  → 강제 매도(또는 매수)가 몰린 봉으로 본다

측정
  이벤트 다음 N봉의 수익률을 **되돌림 방향**으로 집계하고,
  같은 구간의 무조건 평균(기준선)과 비교한다. 기준선보다 커야 엣지다.
  봉인(앞 90일·하락)과 개발(뒤 90일·상승) 양쪽에서 같은 방향이어야 채택.

주의: 수수료 왕복 0.1%를 넘지 못하면 존재해도 쓸 수 없다.
"""
import glob, json, os
import numpy as np, pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_live"
FEE = 0.001
VOL_WIN = 96          # 24시간
FWD = (1, 2, 4, 8, 24)


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


def collect(frames, lo, hi, k_atr, volq):
    """이벤트별 '되돌림 방향 수익률'과 같은 구간 기준선을 모은다."""
    ev = {f: [] for f in FWD}
    base = {f: [] for f in FWD}
    for s, df in frames.items():
        c = df["close"].values
        ret = df["_ret"].values
        atr = df["_atr"].values
        vq = df["_volq"].values
        n = len(c)
        thr = k_atr * (atr / np.where(c == 0, np.nan, c))   # ATR을 비율로
        for i in range(max(lo, VOL_WIN + 1), min(hi, n - max(FWD))):
            if not np.isfinite(thr[i]) or thr[i] <= 0:
                continue
            # 기준선: 모든 봉에서의 전방 수익률(부호 없는 절대 기대값 비교용)
            for f in FWD:
                base[f].append((c[i + f] - c[i]) / c[i])
            if vq[i] < volq:
                continue
            if ret[i] <= -thr[i]:        # 급락 = 롱 청산 캐스케이드 → 반등 기대
                for f in FWD:
                    ev[f].append((c[i + f] - c[i]) / c[i])
            elif ret[i] >= thr[i]:       # 급등 = 숏 청산 캐스케이드 → 하락 기대
                for f in FWD:
                    ev[f].append(-(c[i + f] - c[i]) / c[i])
    return ev, base


def line(ev, base, f):
    a = np.array(ev[f], dtype=float)
    b = np.array(base[f], dtype=float)
    if len(a) < 30:
        return f"{len(a):>6}건  표본부족"
    m = a.mean() * 100
    se = a.std(ddof=1) / np.sqrt(len(a)) * 100
    bm = np.abs(b).mean() * 100
    t = m / se if se > 0 else 0
    net = m - FEE * 100
    return (f"{len(a):>6}건  되돌림 {m:+.3f}%  (±{se:.3f} · t={t:+.1f})  "
            f"수수료후 {net:+.3f}%  {'✅' if net > 0 and abs(t) > 2 else '❌'}")


def main():
    frames = load()
    n0 = len(next(iter(frames.values())))
    mid = n0 // 2
    print(f"  {len(frames)}종목 · {n0}봉 = {n0*15/60/24:.0f}일")
    print(f"  왕복 수수료 {FEE*100:.1f}% · 채택 조건: 수수료 차감 후 양수 + t>2 (양 구간)")

    for k_atr, volq in ((1.5, 0.90), (2.0, 0.95), (3.0, 0.98)):
        print("\n  " + "═" * 76)
        print(f"  이벤트 정의: 1봉 수익률 > ATR×{k_atr}  &  거래량 상위 {(1-volq)*100:.0f}%")
        for nm, lo, hi in (("봉인 앞90일", 0, mid), ("개발 뒤90일", mid, n0)):
            ev, base = collect(frames, lo, hi, k_atr, volq)
            print(f"  ── {nm} ──")
            for f in FWD:
                print(f"     +{f:>2}봉({f*15:>3}분)  {line(ev, base, f)}")


if __name__ == "__main__":
    main()
