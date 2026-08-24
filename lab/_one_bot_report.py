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



# ══════════════════════════════════════════════════════════════════════════
# [2026-08-24] 100건 한도 제거
#
# OKX 청산이력은 한 번에 **최대 100건**이다. 종전에는 한 페이지만 읽어서,
# 청산이 100건을 넘으면 오래된 쪽이 통째로 잘렸다. 실측(8401, 08-20 13:13~):
#   한 페이지  100건 → 37승 63패   ← 37+63=100, 잘렸다는 표시다
#   전량 수집  142건 → 57승 85패
# 42건이 사라져 있었다. 회전이 빠른 OKX 봇(8401·8402·8404)이 특히 위험하다.
#
# 바이낸스 income도 한 번에 1000건이 최대라 같은 방식으로 넘긴다.
# ══════════════════════════════════════════════════════════════════════════
MAX_PAGES = 60          # 안전장치. OKX 6000건 / 바이낸스 60000건이면 충분하다


async def okx_positions_since(ex, since):
    """`since`(ms) 이후의 청산 포지션 전량. 시각 커서로 과거로 넘어간다."""
    seen, after = {}, None
    for _ in range(MAX_PAGES):
        params = {"instType": "SWAP", "limit": "100"}
        if after:
            params["after"] = str(after)
        r = await ex.privateGetAccountPositionsHistory(params)
        rows = r.get("data") or []
        if not rows:
            break
        for x in rows:
            # posId 하나에 부분청산이 여러 건 달릴 수 있어 시각·종목까지 키에 넣는다
            seen[(x.get("posId"), x.get("uTime"), x.get("instId"))] = x
        oldest = min(int(x.get("uTime") or 0) for x in rows)
        if len(rows) < 100 or oldest < since:
            break
        after = oldest
    return [x for x in seen.values() if int(x.get("uTime") or 0) >= since]


async def bnc_income_since(ex, since):
    """`since`(ms) 이후의 income 전량. 시각을 앞으로 밀며 넘어간다."""
    out, seen, start = [], set(), int(since)
    for _ in range(MAX_PAGES):
        rows = await ex.fapiPrivateGetIncome({"startTime": start, "limit": 1000})
        if not rows:
            break
        fresh = 0
        for x in rows:
            k = (x.get("tranId"), x.get("symbol"), x.get("incomeType"), x.get("time"))
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
            fresh += 1
        if len(rows) < 1000:
            break
        newest = max(int(x.get("time") or 0) for x in rows)
        if newest <= start or fresh == 0:
            break
        start = newest        # 경계 건은 위 중복 제거가 거른다
    return out


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
        # posId로 묶지 않는다. OKX는 같은 종목의 **별개 거래에 posId를 재사용**한다
        # (실측 8403: SOL·ORDI·PYTH가 각각 하루 이상 간격의 두 거래에 같은 posId).
        # 묶으면 서로 다른 거래가 한 건으로 합쳐져 승패가 줄어든다.
        for x in await okx_positions_since(ex, since):
            p = float(x.get("realizedPnl") or 0)      # OKX realizedPnl은 수수료·펀딩 포함
            real += p
            fee += abs(float(x.get("fee") or 0))
            fund += float(x.get("fundingFee") or 0)
            wins += p > 0
            losses += p <= 0
    else:
        agg = collections.Counter()
        for x in await bnc_income_since(ex, since):
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
