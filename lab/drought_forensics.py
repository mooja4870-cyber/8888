#!/usr/bin/env python3
"""drought_forensics.py — 무진입이 '우리 변경 탓'인지 '시장 탓'인지 가른다.

질문: 최근 며칠 무진입이 봇 변경의 악영향인가?

가르는 법은 하나뿐이다. **신호가 있었는데 안 들어간 날**과
**신호 자체가 없던 날**을 구분한다.
  · 신호가 있었는데 진입이 없다  → 차단·버그·설정. **우리 탓일 수 있다**
  · 신호가 아예 없었다            → 시장. 설정을 되돌려도 결과는 같다

그리고 반증을 위해 **옛 설정으로 되돌린 반사실**도 같이 센다.
지금 설정이 신호를 죽였다면, 옛 설정에서는 신호가 나와야 한다. 안 나오면
설정은 범인이 아니다.

봇 폴더는 읽기만 한다. 시세는 거래소 공개 API로 직접 받는다.
"""
import asyncio
import datetime as dt
import json
import os
import sys

import ccxt.async_support as ccxt
import numpy as np
import pandas as pd

ROOT = "/Users/l/project"
BOTS = sys.argv[1:] or ["8401", "8402", "8407", "8410"]
DAYS = 12


def _adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def don_signals(d, n, vol_mult, vol_len):
    """일자 → 신호종목수. 채널은 직전 봉까지(자기 자신을 뚫지 않게)."""
    hi = d["high"].rolling(n).max().shift(1)
    lo = d["low"].rolling(n).min().shift(1)
    up, dn = d["close"] > hi, d["close"] < lo
    if vol_mult > 0:
        vm = d["volume"].rolling(vol_len).mean()
        ok = d["volume"] > vm * vol_mult
        up, dn = up & ok, dn & ok
    return (up | dn).values


def dbb_signals(d, n=20, k1=1.0, k2=2.0):
    c = d["close"]
    mid, sd = c.rolling(n).mean(), c.rolling(n).std()
    u1, u2, l1, l2 = mid + k1 * sd, mid + k2 * sd, mid - k1 * sd, mid - k2 * sd
    return (((c > u1) & (c <= u2)) | ((c >= l2) & (c < l1))).values


async def run(bot, ex_cache):
    cfg = json.load(open(f"{ROOT}/{bot}/config.json", encoding="utf-8"))
    venue = str(cfg.get("EXCHANGE_ID", "okx")).lower()
    syms = cfg.get("SYMBOL_WHITELIST") or []
    n = int(cfg.get("DON_LEN", 55))
    vm = float(cfg.get("DON_VOL_MULT", 1.0))
    vl = int(cfg.get("DON_VOL_LEN", 20))
    smap = cfg.get("REGIME_STRATEGY_MAP") or {}

    if venue not in ex_cache:
        ex_cache[venue] = (ccxt.okx if venue == "okx" else ccxt.binance)(
            {"enableRateLimit": True,
             "options": {"defaultType": "swap" if venue == "okx" else "future"}})
    ex = ex_cache[venue]

    ref = "BTC/USDT:USDT"
    btc = await ex.fetch_ohlcv(ref, "1d", limit=300)
    b = pd.DataFrame(btc, columns=["ts", "open", "high", "low", "close", "volume"]).iloc[:-1]
    b["ma"] = b["close"].rolling(200).mean()
    b["adx"] = _adx(b, 14)
    b["day"] = pd.to_datetime(b["ts"], unit="ms").dt.strftime("%Y-%m-%d")
    th = float(cfg.get("REGIME_ADX_THRESHOLD") or 20.0)
    b["reg"] = np.where(b["adx"] < th, "RANGE",
                        np.where(b["close"] > b["ma"], "BULL", "BEAR"))
    regime = dict(zip(b["day"], b["reg"]))

    # 시나리오: 현행 / 거래량필터 해제 / DON_LEN 20 / 관망칸 없음
    scen = {
        "현행": dict(n=n, vm=vm, map=smap),
        f"거래량필터 해제(1.5→0)": dict(n=n, vm=0.0, map=smap),
        f"DON_LEN {n}→20": dict(n=20, vm=vm, map=smap),
    }
    tally = {k: {} for k in scen}
    got = 0
    for s in syms:
        try:
            raw = await ex.fetch_ohlcv(s, "1d", limit=n + 120)
        except Exception:
            continue
        d = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"]).iloc[:-1]
        if len(d) < n + 30:
            continue
        got += 1
        d["day"] = pd.to_datetime(d["ts"], unit="ms").dt.strftime("%Y-%m-%d")
        for name, p in scen.items():
            don = don_signals(d, p["n"], p["vm"], vl)
            dbb = dbb_signals(d)
            for i, day in enumerate(d["day"]):
                reg = regime.get(day)
                if reg is None:
                    continue
                st = (p["map"] or {}).get(reg, "DonchianVol")
                if st in ("관망", None, ""):
                    continue
                hit = dbb[i] if st == "DualBB" else don[i]
                if hit:
                    tally[name][day] = tally[name].get(day, 0) + 1

    days = sorted(regime)[-DAYS:]
    print(f"\n{'='*96}\n  {bot}  ({venue.upper()})  {got}/{len(syms)}종목 · "
          f"DON_LEN {n} · 거래량 {vm}배 · MAP {smap}\n{'='*96}")
    print(f"  {'일자':12}{'국면':7}{'배정':13}" + "".join(f"{k:>22}" for k in scen))
    for day in days:
        reg = regime.get(day, "?")
        st = (smap or {}).get(reg, "DonchianVol")
        row = f"  {day:12}{reg:7}{st:13}"
        for k in scen:
            v = tally[k].get(day, 0)
            row += f"{(str(v)+'건' if v else '—'):>22}"
        print(row)
    tot = {k: sum(tally[k].get(d, 0) for d in days) for k in scen}
    print(f"  {'':32}" + "".join(f"{('합 '+str(tot[k])+'건'):>22}" for k in scen))
    return tot


async def main():
    print(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + f"  무진입 원인 감식 (최근 {DAYS}일)")
    cache = {}
    try:
        for b in BOTS:
            try:
                await run(b, cache)
            except Exception as e:
                print(f"\n  {b} 실패: {type(e).__name__}: {str(e)[:80]}")
    finally:
        for ex in cache.values():
            await ex.close()


if __name__ == "__main__":
    asyncio.run(main())
