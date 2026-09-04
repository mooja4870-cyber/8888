#!/usr/bin/env python3
"""edge_bp.py — 봇의 **건당 엣지를 bp로** 잰다. 수익성 판정의 단일 기준.

왜 bp인가
  손익 USDT 총액은 계좌 크기·복리비율에 휘둘려 전략 자체를 못 본다.
  건당 bp = 실현손익 ÷ 건수 ÷ 명목가 × 10000 은 **신호 자체의 예측력**이다.
  이게 음수면 수수료를 0으로 만들어도 진다. 손절폭·쿨다운·스위칭을 아무리 손봐도
  기하학만 바뀌고 부호는 안 바뀐다. **신호를 손대기 전에 bp부터 재라.**

읽는 법
  신호 총엣지  = 비용 차감 **전** 건당 bp. 이게 0 미만이면 전략을 바꿔야 한다.
  왕복 비용    = 수수료+펀딩 건당 bp. 보통 8~10bp(전량 테이커).
  순엣지       = 둘의 합. 실제로 계좌에 남는 몫.

거래소 원장만 쓴다. 거래이력 CSV는 저가 코인에서 손익 부호가 뒤집힌다
(8888/exchange_pnl.py 참조).

사용법
  python3 lab/edge_bp.py 8401 [일수]
"""
import asyncio
import collections
import datetime as dt
import os
import sys

BASE = "/Users/l/project"
VENUE = {"8401": "okx", "8402": "okx", "8403": "okx", "8404": "okx", "8405": "okx",
         "8407": "binance", "8408": "binance", "8409": "binance", "8410": "binance"}
MAX_PAGES = 60


async def okx_closed(ex, since):
    """OKX 청산 포지션 전량 — 시각 커서로 과거로 넘어간다(한 번에 100건 한도)."""
    seen, after = {}, None
    for _ in range(MAX_PAGES):
        p = {"instType": "SWAP", "limit": "100"}
        if after:
            p["after"] = str(after)
        rows = (await ex.privateGetAccountPositionsHistory(p)).get("data") or []
        if not rows:
            break
        for x in rows:
            seen[(x.get("posId"), x.get("uTime"), x.get("instId"))] = x
        oldest = min(int(x.get("uTime") or 0) for x in rows)
        if len(rows) < 100 or oldest < since:
            break
        after = oldest
    out = []
    for x in seen.values():
        t = int(x.get("uTime") or 0)
        if t < since:
            continue
        # OKX realizedPnl은 수수료·펀딩 포함. 총엣지를 보려면 되돌려야 한다.
        fee = float(x.get("fee") or 0)
        fund = float(x.get("fundingFee") or 0)
        net = float(x.get("realizedPnl") or 0)
        out.append(dict(t=t, gross=net - fee - fund, cost=fee + fund, net=net,
                        notional=abs(float(x.get("openAvgPx") or 0)) * abs(float(x.get("closeTotalPos") or x.get("openMaxPos") or 0))
                                 * float(x.get("ccy") == "USDT" and 1 or 1)))
    return out


async def bnc_closed(ex, since):
    """바이낸스 income — REALIZED_PNL / COMMISSION / FUNDING_FEE를 건별로 묶는다."""
    rows_all, seen, start = [], set(), int(since)
    for _ in range(MAX_PAGES):
        rows = await ex.fapiPrivateGetIncome({"startTime": start, "limit": 1000})
        if not rows:
            break
        new = 0
        for x in rows:
            k = (x.get("tranId"), x.get("time"), x.get("incomeType"), x.get("income"))
            if k in seen:
                continue
            seen.add(k); rows_all.append(x); new += 1
        if len(rows) < 1000 or new == 0:
            break
        start = max(int(x.get("time") or 0) for x in rows) + 1
    out = []
    cost_by_day = collections.defaultdict(float)
    for x in rows_all:
        v = float(x.get("income") or 0)
        t = int(x.get("time") or 0)
        ty = x.get("incomeType")
        if ty == "REALIZED_PNL":
            out.append(dict(t=t, gross=v, cost=0.0, net=v, notional=None))
        elif ty in ("COMMISSION", "FUNDING_FEE"):
            cost_by_day[dt.datetime.fromtimestamp(t / 1000).strftime("%m-%d")] += v
    return out, cost_by_day


async def main():
    bot = sys.argv[1] if len(sys.argv) > 1 else "8401"
    days = float(sys.argv[2]) if len(sys.argv) > 2 else 14.0
    d = os.path.join(BASE, bot)
    sys.path.insert(0, d); os.chdir(d)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(d, ".env"), override=False)
    from core.api_keys import load_api_keys
    load_api_keys(override=True)

    venue = VENUE.get(bot, "okx")
    if venue == "okx":
        from core.exchange import OKXClient as C
        cl = C(os.getenv("OKX_API_KEY", ""), os.getenv("OKX_SECRET_KEY", ""),
               os.getenv("OKX_PASSPHRASE", ""))
    else:
        from core.exchange import BinanceClient as C
        cl = C(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", ""))
    await cl.load_markets()
    ex = cl.exchange

    from core.config import CFG
    b = await cl.get_balance()
    eq = float(b.get("total") or 0)
    lev = float(getattr(CFG, "LEVERAGE", 1))
    pct = float(getattr(CFG, "AUTO_COMPOUND_PCT", 0) or 0) / 100.0
    scale = float(getattr(CFG, "EQUITY_SCALE_FACTOR", 1.0) or 1.0)
    notional = eq * (pct if pct > 0 else 1.0 / max(int(getattr(CFG, "MAX_POSITIONS", 1)), 1)) * scale * lev

    since = int((dt.datetime.now() - dt.timedelta(days=days)).timestamp() * 1000)
    day = collections.defaultdict(lambda: [0.0, 0.0, 0, 0])   # gross, cost, n, wins
    if venue == "okx":
        for x in await okx_closed(ex, since):
            k = dt.datetime.fromtimestamp(x["t"] / 1000).strftime("%m-%d")
            day[k][0] += x["gross"]; day[k][1] += x["cost"]; day[k][2] += 1
            day[k][3] += 1 if x["net"] > 0 else 0
    else:
        trades, cost_by_day = await bnc_closed(ex, since)
        for x in trades:
            k = dt.datetime.fromtimestamp(x["t"] / 1000).strftime("%m-%d")
            day[k][0] += x["gross"]; day[k][2] += 1; day[k][3] += 1 if x["net"] > 0 else 0
        for k, v in cost_by_day.items():
            day[k][1] += v

    print(f"{bot} · 최근 {days:.0f}일 · {venue.upper()} 원장 실측")
    print(f"  잔고 ${eq:.2f} · 레버리지 {lev:.0f}x · 건당 명목가 약 ${notional:.2f}\n")
    print("  %-7s %9s %8s %9s %6s %6s %11s" % ("날짜", "총엣지", "비용", "순", "건수", "승률", "건당bp"))
    tg = tc = tn = tw = 0
    for k in sorted(day):
        g, c, n, w = day[k]
        tg += g; tc += c; tn += n; tw += w
        print("  %-7s %+9.3f %+8.3f %+9.3f %6d %5.0f%% %+11.1f" % (
            k, g, c, g + c, n, (w / n * 100 if n else 0),
            (g / n / notional * 10000 if n and notional else 0)))
    print("  " + "-" * 62)
    if tn:
        print("  %-7s %+9.3f %+8.3f %+9.3f %6d %5.0f%% %+11.1f" % (
            "합계", tg, tc, tg + tc, tn, tw / tn * 100, tg / tn / notional * 10000))
        print()
        print("  신호 총엣지 %+.1f bp/건   (비용 차감 전 — 이게 음수면 전략을 바꿔야 한다)" % (tg / tn / notional * 10000))
        print("  왕복 비용   %+.1f bp/건" % (tc / tn / notional * 10000))
        print("  순엣지      %+.1f bp/건" % ((tg + tc) / tn / notional * 10000))
    else:
        print("  거래 없음")
    await ex.close()


asyncio.run(main())
