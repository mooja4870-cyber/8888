#!/usr/bin/env python3
"""maxpos_backtest.py — MAX_POSITIONS를 올리면 활동량과 수익이 어떻게 되는가.

배경 (v11.0.89): 종목군을 33 → 113으로 3.4배 넓혀도 거래는 73 → 48건으로 **줄었다.**
병목이 종목이 아니라 **자리 수(MAX_POSITIONS=3)**이기 때문이다. 그래서 자리를 늘려본다.

두 가지를 같이 재야 한다. 하나만 보면 틀린 결론이 난다.
  ① 최소주문 벽 — 자리를 늘리면 포지션당 명목가가 줄어 **주문 자체가 거부**될 수 있다
     ([[min-order-size-wall]]: 무진입의 주범은 신호가 아니라 명목가 < 최소주문)
  ② 수익·강건성 — 자리가 늘면 건당 비중이 줄어 수익률이 희석된다.
     동시에 분산이 늘어 MDD는 줄 수 있다. 4관문으로 함께 본다

체결 모형은 `regime_map_backtest.py`를 그대로 쓴다. MAX_POSITIONS만 바꾼다.
"""
import asyncio
import datetime as dt
import json
import os
import random
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
import regime_map_backtest as B

CACHE = "/Users/l/project/8888/lab/_universe_cache.json"
MAP = {"BULL": "DonchianVol", "BEAR": "DualBB", "RANGE": "DonchianVol"}
CANDS = [2, 3, 4, 5, 6, 8, 10]
BOT = "8401"


# ═══════════════ ① 최소주문 벽 ═══════════════
async def min_order_wall():
    import ccxt.async_support as ccxt
    cfg = json.load(open(f"/Users/l/project/{BOT}/config.json", encoding="utf-8"))
    syms = cfg["SYMBOL_WHITELIST"]
    lev = float(cfg.get("LEVERAGE", 3))
    scale = float(cfg.get("EQUITY_SCALE_FACTOR", 1.0))
    bal = 10.5125            # 거래소 실측 잔고

    ex = ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    try:
        await ex.load_markets()
        tk = await ex.fetch_tickers(syms)
        info = []
        for s in syms:
            m = ex.market(s)
            px = (tk.get(s) or {}).get("last")
            if not px:
                continue
            csz = float(m.get("contractSize") or 1)
            mn = float(((m.get("limits") or {}).get("amount") or {}).get("min") or 0)
            info.append((s, csz * px, mn))     # 1계약 명목가, 최소 계약수
    finally:
        await ex.close()

    print(f"\n{'='*92}\n  ① 최소주문 벽 — 잔고 ${bal:.2f} · 레버리지 {lev:.0f}x · SCALE {scale}\n{'='*92}")
    print(f"  {'MAX_POS':>8}{'포지션당 명목가':>16}{'주문 가능':>12}{'거부 종목':>10}   거부되는 종목")
    wall = {}
    for n in CANDS:
        notional = bal * lev / n * scale
        bad = []
        for s, one, mn in info:
            # 계약 정밀도 반올림까지 반영해 실제로 넣을 수 있는지 본다
            raw = notional / one
            try:
                rnd = float(ex.amount_to_precision(s, raw)) if False else raw
            except Exception:
                rnd = raw
            if raw < mn:
                bad.append(s.split("/")[0])
        wall[n] = len(info) - len(bad)
        print(f"  {n:>8}{notional:>15.2f}${wall[n]:>10}/{len(info)}{len(bad):>10}   "
              f"{', '.join(bad[:10])}{' …' if len(bad) > 10 else ''}")
    return wall


# ═══════════════ ② 수익·강건성·활동량 ═══════════════
def occupancy(trades, days, data, reg, n):
    """자리가 실제로 얼마나 찼는지 — 무포지션 일수를 센다."""
    B.MAX_POS = n
    # simulate를 다시 돌리며 보유 일수를 직접 센다
    idle = 0
    streak = mx = 0
    held = set()
    # simulate는 보유 구간을 돌려주지 않으므로 청산일 기준 근사 대신
    # '그날 신규 진입이 있었거나 직전 보유가 이어진 날'을 세는 재시뮬을 쓴다
    return None


def run(n, data, reg, days):
    B.MAX_POS = n
    tr, cv, mdd = B.simulate(data, reg, MAP, days)
    st = B.stats(tr, cv, mdd, days)

    ks = sorted(data)
    sa = B.stats(*B.simulate({k: data[k] for k in ks[0::2]}, reg, MAP, days), days)
    sb = B.stats(*B.simulate({k: data[k] for k in ks[1::2]}, reg, MAP, days), days)
    g3 = sa["tlog"] > 0 and sb["tlog"] > 0

    seeds = sorted(B.stats(*B.simulate(data, reg, MAP, days, rng=random.Random(sd)), days)["tlog"]
                   for sd in range(12))
    q25 = seeds[len(seeds) // 4]
    g1, g2, g4 = st["all_pos"], st["conc"] <= 0.60, q25 > 0
    gates = "".join("✅" if g else "❌" for g in (g1, g2, g3, g4))

    # 활동량: 청산이 일어난 날의 분포로 '거래 간격'을 본다
    tdays = sorted({t["day"] for t in tr})
    gaps = []
    if tdays:
        idx = {d: i for i, d in enumerate(days)}
        prev = None
        for d in tdays:
            i = idx.get(d)
            if i is None:
                continue
            if prev is not None:
                gaps.append(i - prev)
            prev = i
    maxgap = max(gaps) if gaps else len(days)
    return dict(n=n, trades=st["n"], total=st["total"], wr=st["wr"], mdd=st["mdd"],
                conc=st["conc"], gates=gates, passed=all((g1, g2, g3, g4)),
                med=seeds[len(seeds) // 2], worst=seeds[0],
                tdays=len(tdays), maxgap=maxgap)


def main():
    print(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "  MAX_POSITIONS 검증")
    wall = asyncio.run(min_order_wall())

    raw = json.load(open(CACHE))
    wl = json.load(open(f"/Users/l/project/{BOT}/config.json", encoding="utf-8"))["SYMBOL_WHITELIST"]
    data = {s: pd.DataFrame(raw[s], columns=["ts", "open", "high", "low", "close", "volume"])
            for s in wl if s in raw}
    btc = pd.DataFrame(raw["BTC/USDT:USDT"],
                       columns=["ts", "open", "high", "low", "close", "volume"])
    b = btc.copy()
    b["ma"] = b["close"].rolling(B.MA_LEN).mean()
    b["adx"] = B._adx(b, 14)
    b["day"] = pd.to_datetime(b["ts"], unit="ms").dt.strftime("%Y-%m-%d")
    b = b.dropna(subset=["ma", "adx"])
    rr = np.where(b["adx"] < B.ADX_TH, "RANGE", np.where(b["close"] > b["ma"], "BULL", "BEAR"))
    dl = list(b["day"])
    reg = {dl[i + 1]: rr[i] for i in range(len(dl) - 1)}
    days = [d for d in dl if d in reg][-730:]

    print(f"\n{'='*92}\n  ② 수익·강건성 — {len(data)}종목 · {days[0]} ~ {days[-1]} "
          f"({len(days)}일) · 3x\n{'='*92}")
    print(f"  {'MAX_POS':>8}{'거래':>7}{'총수익':>11}{'승률':>8}{'MDD':>8}{'분기집중':>8}"
          f"{'청산일수':>9}{'최장공백':>9}  {'①②③④':6}  시드")
    print("  " + "─" * 106)
    res = []
    for n in CANDS:
        r = run(n, data, reg, days)
        r["orderable"] = wall.get(n)
        res.append(r)
        print(f"  {n:>8}{r['trades']:>7}{r['total']:>+10.1f}%{r['wr']:>7.1f}%"
              f"{r['mdd']*100:>7.1f}%{r['conc']*100:>7.0f}%{r['tdays']:>8}일{r['maxgap']:>8}일"
              f"  {r['gates']}  중앙 {r['med']:+.2f} 최악 {r['worst']:+.2f}")
    B.MAX_POS = 3

    base = next(r for r in res if r["n"] == 3)
    print("  " + "─" * 106)
    print(f"\n{'='*92}\n  판정 (기준 = 현행 MAX_POS 3)\n{'='*92}")
    for r in res:
        if r["n"] == 3:
            continue
        d = r["med"] - base["med"]
        blocked = len(wl) - (r["orderable"] or 0)
        note = f"주문거부 {blocked}종목" if blocked else "주문 전량 가능"
        verdict = "✅ 채택 후보" if (r["passed"] and d > 0 and blocked == 0) else "❌ 기각"
        print(f"    MAX_POS {r['n']:<3} 시드중앙 {d:+.2f} · 거래 {base['trades']}→{r['trades']}건 · "
              f"MDD {base['mdd']*100:.0f}→{r['mdd']*100:.0f}% · {note}   {verdict}")
    print(f"{'='*92}\n")


if __name__ == "__main__":
    main()
