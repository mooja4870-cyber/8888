#!/usr/bin/env python3
"""filter_backtest_15m.py — 실제 체결된 거래에 진입 필터를 **소급 적용**해 효과를 잰다.

왜 이 방식인가
  8407은 딥러닝 방향예측, 8409는 TSMOM이라 신호를 재현할 수 없다.
  대신 **거래소에 남은 실제 거래**를 가져와, 각 거래의 진입 시각에 필터 조건이
  참이었는지 판정하고 통과/탈락 그룹의 성과를 비교한다.
  "이 필터를 켰다면 우리 거래가 어떻게 됐을까"를 직접 답한다.
  신호를 흉내내지 않으므로 재현 오차가 없다.

검증 대상 (제미나이 제안 ③④)
  ③ ADX 필터   진입 시각의 1시간봉 ADX(14) ≥ 문턱일 때만 진입
  ④ MTF 정렬   진입 방향이 1시간봉 EMA20 방향과 일치할 때만 진입
                (롱이면 종가>EMA20, 숏이면 종가<EMA20)

판정 기준 — 결과 보기 전에 확정
  ① 필터 통과 그룹의 **승률**이 전체보다 높을 것
  ② 필터 통과 그룹의 **건당 손익**이 전체보다 높을 것
  ③ 통과 건수가 전체의 **30% 이상**일 것 (너무 줄면 표본이 죽는다)
  셋을 다 넘겨야 채택. 하나라도 미달이면 기각한다.

미래참조 차단: 진입 시각 **직전에 닫힌** 1시간봉으로만 판정한다.
"""
import asyncio
import datetime as dt
import os
import statistics as st
import sys

import numpy as np
import pandas as pd

BASE = "/Users/l/project"


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    p = np.where((up > dn) & (up > 0), up, 0.0)
    m = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(p, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * pd.Series(m, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


async def closed_trades(ex, symbols, since):
    """체결 목록을 순회하며 포지션 단위로 (진입시각, 방향, 실현손익)을 복원한다."""
    out = []
    for sym in symbols:
        try:
            fills = await ex.fetch_my_trades(sym, since=since, limit=1000)
        except Exception:
            continue
        pos = 0.0
        entry_ts = None
        entry_side = None
        pnl = 0.0
        for f in sorted(fills, key=lambda x: x["timestamp"]):
            amt = float(f.get("amount") or 0)
            side = f.get("side")
            rp = float((f.get("info") or {}).get("realizedPnl") or 0)
            signed = amt if side == "buy" else -amt
            if pos == 0 and abs(signed) > 0:          # 신규 진입
                entry_ts = f["timestamp"]
                entry_side = "long" if signed > 0 else "short"
                pnl = 0.0
            pos += signed
            pnl += rp
            if abs(pos) < 1e-12 and entry_ts:         # 청산 완료
                out.append(dict(sym=sym, ts=entry_ts, side=entry_side, pnl=pnl))
                entry_ts = None
                pos = 0.0
                pnl = 0.0
    return out


async def main():
    bot = sys.argv[1] if len(sys.argv) > 1 else "8409"
    days = float(sys.argv[2]) if len(sys.argv) > 2 else 14.0
    d = os.path.join(BASE, bot)
    sys.path.insert(0, d); os.chdir(d)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(d, ".env"), override=False)
    from core.api_keys import load_api_keys
    load_api_keys(override=True)
    from core.config import CFG
    from core.exchange import BinanceClient

    cl = BinanceClient(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", ""))
    await cl.load_markets()
    ex = cl.exchange
    syms = CFG.SYMBOL_WHITELIST or []
    since = int((dt.datetime.now() - dt.timedelta(days=days)).timestamp() * 1000)

    trades = await closed_trades(ex, syms, since)
    if not trades:
        print("  거래 없음"); await ex.close(); return

    # 종목별 1시간봉 지표 (진입 시각 직전 봉)
    ind = {}
    for s in set(t["sym"] for t in trades):
        try:
            o = await ex.fetch_ohlcv(s, "1h", since=since - 86400000 * 3, limit=1000)
        except Exception:
            continue
        if not o:
            continue
        df = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
        df["adx"] = adx(df, 14)
        df["ema20"] = ema(df["close"], 20)
        ind[s] = df

    rows = []
    for t in trades:
        df = ind.get(t["sym"])
        if df is None:
            continue
        prev = df[df["ts"] < t["ts"]]       # 진입 직전에 닫힌 봉만
        if len(prev) < 25:
            continue
        r = prev.iloc[-1]
        if not (np.isfinite(r["adx"]) and np.isfinite(r["ema20"])):
            continue
        aligned = (r["close"] > r["ema20"]) if t["side"] == "long" else (r["close"] < r["ema20"])
        rows.append(dict(pnl=t["pnl"], adx=float(r["adx"]), aligned=bool(aligned)))
    D = pd.DataFrame(rows)
    if D.empty:
        print("  판정 가능한 거래 없음"); await ex.close(); return

    def rep(name, sub, full):
        n = len(sub)
        if n == 0:
            print("  %-24s 통과 0건" % name); return
        wr = (sub["pnl"] > 0).mean() * 100
        per = sub["pnl"].mean()
        keep = n / len(full) * 100
        ok = wr > base_wr and per > base_per and keep >= 30
        miss = "".join(x for x, c in [("①", wr > base_wr), ("②", per > base_per),
                                      ("③", keep >= 30)] if not c)
        print("  %-24s %4d건(%3.0f%%)  승률 %5.1f%%  건당 %+8.5f  %s" % (
            name, n, keep, wr, per, "✅ 통과" if ok else "❌ " + miss))

    base_wr = (D["pnl"] > 0).mean() * 100
    base_per = D["pnl"].mean()
    print("%s · 최근 %.0f일 · 판정 가능 거래 %d건" % (bot, days, len(D)))
    print("  기준선(전체)            %4d건(100%%)  승률 %5.1f%%  건당 %+8.5f\n" % (
        len(D), base_wr, base_per))
    for th in (15, 20, 25, 30):
        rep("③ 1h ADX ≥ %d" % th, D[D["adx"] >= th], D)
    rep("④ 1h EMA20 정렬", D[D["aligned"]], D)
    rep("③+④ ADX≥20 & 정렬", D[(D["adx"] >= 20) & D["aligned"]], D)
    await ex.close()


asyncio.run(main())
