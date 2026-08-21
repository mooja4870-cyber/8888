#!/usr/bin/env python3
"""
lab_run.py — 전략 후보 실험실 (개발/봉인 분리)

지금까지 실패한 방식
────────────────────
같은 데이터에 전략을 여러 개 돌려 "플러스인 것"을 골라 배포했다. 그러면 엣지가 아니라
그 기간에 맞춘 것을 고르게 된다(8407 실측: 백테스트 1시간봉 +14.9%/월 → 실거래 25시간 0건).

그래서 데이터를 둘로 나눈다
──────────────────────────
  개발 구간 (앞 2/3, 60일) — 여기서만 탐색·조정한다
  봉인 구간 (뒤 1/3, 30일) — 손대지 않는다. 최종 후보를 딱 한 번 통과시킨다.
봉인 구간에서 무너지면 폐기한다. 여기서 다시 조정하면 봉인의 의미가 사라진다.

청산 모형은 실제 봇과 같은 순서를 태운다(본전보호 → 분할익절 → 샹들리에 트레일링 →
시간청산). 단순 SL/TP만 보면 실거래와 크게 어긋난다(실측: 승률 31% vs 실거래 57%).

사용
────
    python3 lab_run.py            # 전 후보 실행
    python3 lab_run.py <이름>     # 특정 후보만
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

CACHE_DIR = "/Users/l/project/8888/lab_cache"
FEE = 0.001              # 왕복 수수료·슬리피지 0.1%/건
DEV_RATIO = 2.0 / 3.0    # 앞 2/3 = 개발, 뒤 1/3 = 봉인
BAR_MIN = 15

# 실제 봇의 청산 설정(8408 기준)
EXIT = dict(be_trig=0.012, be_prot=0.001, pt_trig=0.015, pt_frac=0.5,
            k_ch=3.0, hold_bars=int(6 * 60 / BAR_MIN))


def load():
    out = {}
    for p in sorted(glob.glob(os.path.join(CACHE_DIR, "binance_15m_*.json"))):
        raw = json.load(open(p))
        df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        c, h, l = df["close"], df["high"], df["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        df["atr"] = tr.ewm(span=14, adjust=False).mean()
        df["atr_pct"] = df["atr"] / c
        sym = os.path.basename(p).split("15m_")[1].replace(".json", "").split("_USDT")[0]
        out[sym] = df
    return out


def simulate(sigs, df, hold_bars=None, k_ch=None, pure_trail=False):
    """실제 봇 청산 경로 재현. sigs = [(i, dir, risk, rr), ...]

    보유시간과 트레일링 계수를 후보별로 달리 준다. 추세추종은 6시간 안에 결판나지 않으므로
    되돌림 전략과 같은 보유시간을 쓰면 추세를 타기도 전에 시간청산으로 잘린다.
    """
    hb = hold_bars if hold_bars is not None else EXIT["hold_bars"]
    kc = k_ch if k_ch is not None else EXIT["k_ch"]
    # pure_trail: 본전보호·분할익절을 끄고 손절→트레일링만 태운다.
    # 실측(돈치안 개발구간): 본전보호를 켜면 평균 승이 +0.82%로 잘려 손익비 0.21(-222%),
    # 끄면 평균 승 +9.18%로 손익비 2.30(+305%). 승률은 78%→37%로 떨어지지만
    # 추세추종은 큰 승리 몇 건이 전부라 본전보호가 그 몇 건을 죽인다.
    h, l, c, atr = df["high"].values, df["low"].values, df["close"].values, df["atr"].values
    n = len(df)
    res, busy = [], -1
    for i, d, risk, rr in sigs:
        if i <= busy or risk <= 0:
            continue
        e = c[i]
        long = d == "long"
        sl = e * (1 - risk) if long else e * (1 + risk)
        tp = e * (1 + risk * rr) if long else e * (1 - risk * rr)
        realized, remain, part, trail, peak = 0.0, 1.0, False, False, e
        end = min(n - 1, i + hb)
        j, done = i + 1, False
        while j <= end:
            hi, lo = h[j], l[j]
            gain = (hi - e) / e if long else (e - lo) / e
            if not pure_trail and gain >= EXIT["be_trig"]:
                sl = max(sl, e * (1 + EXIT["be_prot"])) if long else min(sl, e * (1 - EXIT["be_prot"]))
            if pure_trail and not trail and gain >= EXIT["pt_trig"]:
                trail = True
                peak = hi if long else lo
            if not pure_trail and not part and gain >= EXIT["pt_trig"]:
                realized += EXIT["pt_frac"] * EXIT["pt_trig"]
                remain -= EXIT["pt_frac"]
                part = trail = True
                peak = hi if long else lo
            if trail:
                peak = max(peak, hi) if long else min(peak, lo)
                a = atr[j] if atr[j] == atr[j] else 0.0
                ch = peak - kc * a if long else peak + kc * a
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
        res.append(realized)
        busy = min(j, end)
    return res


def score(res, days):
    if not res:
        return dict(n=0, wr=0.0, net=0.0, mo=0.0)
    net = sum(res) - FEE * len(res)
    return dict(n=len(res), wr=100.0 * sum(1 for x in res if x > 0) / len(res),
                net=net * 100, mo=net * 100 * 30 / days)


# ── 전략 후보들 ─────────────────────────────────────────────
# 1차 실험에서 5개 후보가 전부 대폭 손실이었다. 원인은 회전이었다.
#   손절폭이 ATR×1.5 ≈ 0.75%인데 왕복 수수료가 0.1% → **리스크의 13%가 수수료**.
#   여기에 하루 26~86건을 돌리니 수수료만으로 손실 전액이 설명됐다.
# 그래서 구조를 바꾼다: 손절을 넓게(ATR×4~6) 잡아 수수료 비중을 3~5%로 낮추고,
# 진입을 훨씬 엄격하게 걸어 건수를 줄이고, 추세가 자랄 시간을 준다(보유 24~72시간).
# 각 후보는 (신호목록, 청산옵션)을 반환한다.

def _atr_ok(ap, i, floor=0.004):
    return ap[i] == ap[i] and ap[i] >= floor


def cand_donchian(df, lo, hi, p=192, atr_sl=4.0, rr=3.0, hold=192, kch=4.0, vol_mult=1.5):
    """장기 돈치안 돌파 — 48시간 고점/저점을 거래량 급증과 함께 이탈할 때만."""
    c, h, l, v = (df[k].values for k in ("close", "high", "low", "volume"))
    ap = df["atr_pct"].values
    hh = pd.Series(h).rolling(p).max().shift(1).values
    ll = pd.Series(l).rolling(p).min().shift(1).values
    vm = pd.Series(v).rolling(96).mean().shift(1).values
    out = []
    for i in range(max(p + 2, lo), hi):
        if not _atr_ok(ap, i) or not (vm[i] == vm[i]) or vm[i] <= 0:
            continue
        if v[i] < vm[i] * vol_mult:          # 거래량이 실리지 않은 돌파는 버린다
            continue
        if c[i] > hh[i]:
            out.append((i, "long", ap[i] * atr_sl, rr))
        elif c[i] < ll[i]:
            out.append((i, "short", ap[i] * atr_sl, rr))
    return out, {"hold": hold, "kch": kch, "pure": True}


def cand_trend_pullback(df, lo, hi, ema_f=96, ema_s=384, atr_sl=4.0, rr=3.0, hold=192, kch=4.0):
    """추세 눌림목 — 장기 정배열에서 단기선까지 눌렸다 반등하는 첫 봉만."""
    c = df["close"].values
    ap = df["atr_pct"].values
    ef = pd.Series(c).ewm(span=ema_f, adjust=False).mean().values
    es = pd.Series(c).ewm(span=ema_s, adjust=False).mean().values
    out = []
    for i in range(max(ema_s + 2, lo), hi):
        if not _atr_ok(ap, i):
            continue
        up = ef[i] > es[i] and c[i] > es[i]
        dn = ef[i] < es[i] and c[i] < es[i]
        if up and c[i - 1] <= ef[i - 1] and c[i] > ef[i]:      # 단기선 회복 첫 봉
            out.append((i, "long", ap[i] * atr_sl, rr))
        elif dn and c[i - 1] >= ef[i - 1] and c[i] < ef[i]:
            out.append((i, "short", ap[i] * atr_sl, rr))
    return out, {"hold": hold, "kch": kch, "pure": True}


def cand_squeeze_break(df, lo, hi, p=96, sq=0.7, atr_sl=4.0, rr=3.0, hold=288, kch=4.0):
    """변동성 수축 후 돌파 — 1차 실험에서 유일하게 손실이 작았던(-9%) 계열을 확장."""
    c, h, l = (df[k].values for k in ("close", "high", "low"))
    ap = df["atr_pct"].values
    apm = pd.Series(ap).rolling(p * 3).mean().values
    hh = pd.Series(h).rolling(p).max().shift(1).values
    ll = pd.Series(l).rolling(p).min().shift(1).values
    out = []
    for i in range(max(p * 3 + 2, lo), hi):
        if not (apm[i] == apm[i]) or ap[i] <= 0 or apm[i] <= 0:
            continue
        if ap[i] > apm[i] * sq:
            continue
        if c[i] > hh[i]:
            out.append((i, "long", ap[i] * atr_sl, rr))
        elif c[i] < ll[i]:
            out.append((i, "short", ap[i] * atr_sl, rr))
    return out, {"hold": hold, "kch": kch, "pure": True}


def cand_meanrev_extreme(df, lo, hi, p=96, k=3.0, atr_sl=4.0, rr=2.0, hold=96, kch=3.0):
    """극단 되돌림(대조군) — 현행 봇 계열. 저빈도·광폭손절로 다시 재보기."""
    c = df["close"].values
    ap = df["atr_pct"].values
    ma = pd.Series(c).rolling(p).mean().values
    sd = pd.Series(c).rolling(p).std().values
    out = []
    for i in range(max(p + 2, lo), hi):
        if not _atr_ok(ap, i) or not (sd[i] == sd[i]) or sd[i] <= 0:
            continue
        z = (c[i] - ma[i]) / sd[i]
        if z <= -k:
            out.append((i, "long", ap[i] * atr_sl, rr))
        elif z >= k:
            out.append((i, "short", ap[i] * atr_sl, rr))
    return out, {"hold": hold, "kch": kch, "pure": True}


CANDS = {
    "돈치안48h+거래량":   lambda d, a, b: cand_donchian(d, a, b),
    "돈치안24h+거래량":   lambda d, a, b: cand_donchian(d, a, b, p=96),
    "추세눌림목":         lambda d, a, b: cand_trend_pullback(d, a, b),
    "수축후돌파(확장)":   lambda d, a, b: cand_squeeze_break(d, a, b),
    "극단되돌림(대조군)": lambda d, a, b: cand_meanrev_extreme(d, a, b),
}


def evaluate(fn, frames, lo_r, hi_r, label):
    """구간 [lo_r, hi_r) 비율 범위를 평가. 3분할 결과도 함께 낸다."""
    tot, segs = [], [[], [], []]
    days = 0
    for sym, df in frames.items():
        n = len(df)
        lo, hi = int(n * lo_r), int(n * hi_r)
        days = (hi - lo) * BAR_MIN / 60 / 24
        sigs, opt = fn(df, lo, hi)
        r = simulate(sigs, df, opt.get("hold"), opt.get("kch"), opt.get("pure", False))
        tot += r
        # 구간 3분할 (신호 인덱스 기준)
        third = (hi - lo) // 3
        for k in range(3):
            s2 = [s for s in sigs if lo + k * third <= s[0] < lo + (k + 1) * third]
            segs[k] += simulate(s2, df, opt.get("hold"), opt.get("kch"), opt.get("pure", False))
    o = score(tot, days)
    ss = [score(s, days / 3) for s in segs]
    return o, ss, days


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    frames = load()
    if not frames:
        print("  캐시 없음 — lab_data.py 먼저 실행"); return
    n0 = len(next(iter(frames.values())))
    print(f"  {len(frames)}종목 · {n0}봉 · 총 {n0*BAR_MIN/60/24:.0f}일")
    print(f"  개발 구간 앞 {DEV_RATIO*100:.0f}% / 봉인 구간 뒤 {(1-DEV_RATIO)*100:.0f}%  (봉인은 최종 1회만 사용)")
    print("  " + "═" * 74)
    print(f"  {'후보':<18}{'건수':>6}{'승률':>7}{'순손익':>10}{'월환산':>9}   구간3분할")
    print("  " + "─" * 74)
    results = {}
    for name, fn in CANDS.items():
        if only and only not in name:
            continue
        o, ss, days = evaluate(fn, frames, 0.0, DEV_RATIO, name)
        seg = " ".join(f"{'+' if s['net']>0 else '-'}" for s in ss)
        allpos = all(s["net"] > 0 for s in ss)
        print(f"  {name:<18}{o['n']:>6}{o['wr']:>6.0f}%{o['net']:>+9.2f}%{o['mo']:>+8.1f}%   {seg} {'✅' if allpos else ''}")
        results[name] = (o, ss, allpos)
    print("  " + "─" * 74)
    good = [k for k, v in results.items() if v[2] and v[0]["net"] > 0]
    print(f"  개발 구간 통과(3구간 전부 플러스): {good if good else '없음'}")


if __name__ == "__main__":
    main()
