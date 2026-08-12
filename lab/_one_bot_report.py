#!/usr/bin/env python3
"""_one_bot_report.py — 봇 하나의 거래소 원장 성과를 JSON 한 줄로 출력.

봇마다 `core` 패키지가 다르므로 한 프로세스에서 여러 봇을 임포트하면
먼저 로드된 모듈이 캐시돼 다른 봇 값이 그대로 나온다(실측: 8403이 8401과 동일).
그래서 봇당 별도 프로세스로 실행하고, 결과만 표준출력으로 넘긴다.
"""
import asyncio, collections, json, os, sys, time

d, venue = sys.argv[1], sys.argv[2]
sys.path.insert(0, d)
os.chdir(d)
from dotenv import load_dotenv
load_dotenv(os.path.join(d, ".env"), override=False)
from core.api_keys import load_api_keys
load_api_keys(override=True)


async def main():
    if venue == "okx":
        from core.exchange import OKXClient as C
        cl = C(os.getenv("OKX_API_KEY", ""), os.getenv("OKX_SECRET_KEY", ""),
               os.getenv("OKX_PASSPHRASE", ""))
    else:
        from core.exchange import BinanceClient as C
        cl = C(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", ""))
    await cl.load_markets()
    ex = cl.exchange
    s = json.load(open("data/stats.json"))
    seed = float(s.get("seed_money") or 0)
    ps = s.get("perf_start_time", "")
    since = int(time.mktime(time.strptime(ps, "%Y-%m-%d %H:%M:%S")) * 1000)

    wins = losses = 0
    real = fee = fund = 0.0
    if venue == "okx":
        r = await ex.privateGetAccountPositionsHistory({"instType": "SWAP", "limit": "100"})
        for x in (r.get("data") or []):
            if int(x.get("uTime") or 0) < since:
                continue
            p = float(x.get("realizedPnl") or 0)      # OKX realizedPnl은 수수료·펀딩 포함
            real += p
            fee += abs(float(x.get("fee") or 0))
            fund += float(x.get("fundingFee") or 0)
            wins += p > 0
            losses += p <= 0
    else:
        inc = await ex.fapiPrivateGetIncome({"startTime": since, "limit": 1000})
        agg = collections.Counter()
        for x in inc:
            v = float(x.get("income") or 0)
            agg[x.get("incomeType")] += v
            if x.get("incomeType") == "REALIZED_PNL":
                if v > 0: wins += 1
                elif v < 0: losses += 1
        real = agg["REALIZED_PNL"] + agg["COMMISSION"] + agg["FUNDING_FEE"]
        fee, fund = abs(agg["COMMISSION"]), agg["FUNDING_FEE"]

    b = await ex.fetch_balance()
    total = float((b.get("USDT") or {}).get("total") or 0)
    pos = [p for p in await ex.fetch_positions() if float(p.get("contracts") or 0) != 0]
    unreal = sum(float(p.get("unrealizedPnl") or 0) for p in pos)
    await ex.close()
    print("JSON" + json.dumps(dict(
        bot=os.path.basename(d), seed=seed, real=real, fee=fee, fund=fund,
        unreal=unreal, total=total, pos=len(pos), wins=wins, losses=losses,
        ps=ps, hours=(time.time() - since / 1000) / 3600.0)))


asyncio.run(main())
