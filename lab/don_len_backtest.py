#!/usr/bin/env python3
"""don_len_backtest.py — 돈치안 채널 길이(DON_LEN)를 실측으로 고른다.

왜 필요한가
  8402·8401·8410이 쓰는 `DON_LEN=55`는 **내가 국면 라우터를 만들며 넣은 값**이고
  (커밋 949133e), 근거는 터틀 트레이딩 System 2의 관례일 뿐이다.
  이 종목군·이 타임프레임에서 55가 맞는지 확인한 적이 없다.

설계 (메모리 backtest-sample-window 원칙 준수)
  · 2년 일봉 — 7개월은 국면 운을 엣지로 오인한다
  · 4분할 전부 양수여야 채택 — 한 구간의 운을 걸러낸다
  · 인접값 안정성 — 20/30/40/55가 완만해야 신뢰한다. 널뛰면 과최적화다
  · 미래참조 차단 — 확정봉만 쓰고 진입은 **다음 봉 시가**로 잡는다

한계
  · MAX_POSITIONS·최소주문·슬리피지는 반영하지 못한다(개별 거래 독립 가정)
  · 실제 봇은 국면 갱신에 TTL이 있으나 여기서는 매봉 재판정한다
"""
import asyncio, json, os, sys, datetime as dt
import numpy as np, pandas as pd

BOT = "8402"
CFG = json.load(open(f"/Users/l/project/{BOT}/config.json"))
WL = CFG.get("SYMBOL_WHITELIST") or []
VOL_LEN = int(CFG.get("DON_VOL_LEN", 20))
VOL_MULT = float(CFG.get("DON_VOL_MULT", 1.5))
SL_MULT = float(CFG.get("DON_SL_ATR_MULT", 2.0))
TP_MULT = float(CFG.get("DON_TP_ATR_MULT", 4.0))
MA_LEN = int(CFG.get("REGIME_MA_LEN", 200))
ADX_TH = float(CFG.get("REGIME_ADX_THRESHOLD", 20.0))
FEE = 0.10                      # 왕복 %
CACHE = "/Users/l/project/8888/lab/_don_cache.json"


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    p = np.where((up > dn) & (up > 0), up, 0.0)
    m = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(p, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * pd.Series(m, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


async def fetch_all():
    import ccxt.async_support as ccxt
    ex = ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    await ex.load_markets()
    out = {}
    syms = ["BTC/USDT:USDT"] + [s for s in WL if s != "BTC/USDT:USDT"]
    for s in syms:
        rows, since = [], int((dt.datetime.now() - dt.timedelta(days=760)).timestamp() * 1000)
        for _ in range(12):
            try:
                o = await ex.fetch_ohlcv(s, "1d", since=since, limit=300)
            except Exception:
                break
            if not o:
                break
            rows += o
            if len(o) < 300:
                break
            since = o[-1][0] + 86400000
        if len(rows) > 250:
            seen, ded = set(), []
            for r in rows:
                if r[0] in seen:
                    continue
                seen.add(r[0]); ded.append(r)
            out[s] = sorted(ded, key=lambda x: x[0])
    await ex.close()
    return out


def simulate(data, don_len):
    """DON_LEN으로 신호를 재생성해 거래 목록을 만든다. 반환: [(ts, ret%)]"""
    btc = pd.DataFrame(data["BTC/USDT:USDT"], columns=["ts", "open", "high", "low", "close", "vol"])
    btc["ma"] = btc["close"].rolling(MA_LEN).mean()
    btc["adx"] = adx(btc)
    bull = {}
    for i in range(len(btc)):
        r = btc.iloc[i]
        bull[int(r["ts"])] = bool(r["close"] > r["ma"] and r["adx"] >= ADX_TH) \
            if np.isfinite(r["ma"]) and np.isfinite(r["adx"]) else False

    trades = []
    for sym, raw in data.items():
        if sym == "BTC/USDT:USDT" and sym not in WL:
            continue
        d = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "vol"])
        if len(d) < don_len + 60:
            continue
        d["atr"] = atr(d)
        d["hh"] = d["high"].rolling(don_len).max().shift(1)   # 직전 N봉 고가
        d["vm"] = d["vol"].rolling(VOL_LEN).mean().shift(1)
        i = don_len + 30
        while i < len(d) - 1:
            r = d.iloc[i]
            # 확정봉 r로 판정 → 진입은 **다음 봉 시가**
            if (np.isfinite(r["hh"]) and np.isfinite(r["vm"]) and np.isfinite(r["atr"])
                    and r["close"] > r["hh"] and r["vol"] > r["vm"] * VOL_MULT
                    and bull.get(int(r["ts"]), False)):
                ep = float(d.iloc[i + 1]["open"])
                a = float(r["atr"])
                if ep <= 0 or a <= 0:
                    i += 1; continue
                sl, tp = ep - a * SL_MULT, ep + a * TP_MULT
                ret = None
                for j in range(i + 1, min(i + 1 + 60, len(d))):
                    b = d.iloc[j]
                    if b["low"] <= sl:
                        ret = (sl / ep - 1) * 100; break
                    if b["high"] >= tp:
                        ret = (tp / ep - 1) * 100; break
                if ret is None:
                    ret = (float(d.iloc[min(i + 60, len(d) - 1)]["close"]) / ep - 1) * 100
                trades.append((int(r["ts"]), ret - FEE))
                i = j if ret is not None else i + 1     # 청산 후 재탐색
            i += 1
    return sorted(trades)


async def main():
    if os.path.exists(CACHE):
        data = json.load(open(CACHE))
        print(f"캐시 사용 ({len(data)}종목)")
    else:
        print("일봉 수집 중...")
        data = await fetch_all()
        json.dump(data, open(CACHE, "w"))
        print(f"수집 완료 {len(data)}종목")
    n_days = max(len(v) for v in data.values())
    print(f"기간 약 {n_days}일 ({n_days/365:.1f}년) · 종목 {len(data)}개\n")

    print(f"  {'DON':>4} {'거래':>5} {'승률':>7} {'건당%':>8} {'총합%':>9}   "
          f"{'Q1':>7} {'Q2':>7} {'Q3':>7} {'Q4':>7}  판정")
    for L in (20, 30, 40, 55):
        tr = simulate(data, L)
        if not tr:
            print(f"  {L:4d}   거래 0건"); continue
        rets = [r for _, r in tr]
        n = len(rets); w = sum(1 for r in rets if r > 0)
        ts = [t for t, _ in tr]
        lo, hi = min(ts), max(ts)
        qs = [[] for _ in range(4)]
        for t, r in tr:
            k = min(3, int((t - lo) / max(1, (hi - lo)) * 4))
            qs[k].append(r)
        qsum = [sum(q) for q in qs]
        ok = all(x > 0 for x in qsum)
        print(f"  {L:4d} {n:5d} {w/n*100:6.1f}% {sum(rets)/n:+8.3f} {sum(rets):+9.1f}   "
              + " ".join(f"{x:+7.1f}" for x in qsum)
              + f"  {'✅ 4분할 양수' if ok else '❌ 기각'}")

asyncio.run(main())
