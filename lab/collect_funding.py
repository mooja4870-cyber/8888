#!/usr/bin/env python3
"""collect_funding.py — 61종목 180일 펀딩비 이력 수집

왜 펀딩비인가
────────────
가격 패턴에서 엣지를 찾는 시도는 8전 8패했다. 패턴은 누구나 보고, 보이는 순간
사라진다. 반면 펀딩비는 **한쪽이 반드시 비용을 치르는 구조**다. 무기한 선물에서
롱이 몰리면 롱이 숏에게 8시간마다 돈을 낸다. 이건 예측이 아니라 계약 조건이다.

가설: 펀딩비가 극단으로 치우친 종목은 그 방향 포지션이 과밀하다. 과밀한 쪽은
청산에 취약하므로 **반대 방향으로 되돌림이 나타난다**.

이 스크립트는 검증에 필요한 원자료(8시간 간격 펀딩비)만 모은다.
판정은 verify_funding_edge.py가 한다.
"""
import glob, json, os, sys, time

BOT = "/Users/l/project/8401"          # OKX 클라이언트 재사용
CACHE = "/Users/l/project/8888/lab_cache_live"
OUT = "/Users/l/project/8888/lab_funding_hist"
DAYS = 180

sys.path.insert(0, BOT)
os.chdir(BOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(BOT, ".env"), override=False)
from core.api_keys import load_api_keys
load_api_keys(override=True)

import asyncio


def symbols():
    out = []
    for p in sorted(glob.glob(f"{CACHE}/okx_15m_*.json")):
        s = os.path.basename(p).replace("okx_15m_", "").replace(".json", "")
        out.append(f"{s}/USDT:USDT")
    return out


async def main():
    from core.exchange import OKXClient
    cl = OKXClient(os.getenv("OKX_API_KEY", ""), os.getenv("OKX_SECRET_KEY", ""),
                   os.getenv("OKX_PASSPHRASE", ""))
    await cl.load_markets()
    ex = cl.exchange
    os.makedirs(OUT, exist_ok=True)
    syms = symbols()
    print(f"  {len(syms)}종목 · {DAYS}일 펀딩비 수집", flush=True)
    start = int((time.time() - DAYS * 86400) * 1000)

    ok = fail = 0
    for n, sym in enumerate(syms, 1):
        name = sym.split("/")[0]
        path = os.path.join(OUT, f"{name}.json")
        if os.path.exists(path):
            ok += 1
            continue
        rows, since = [], start
        try:
            while True:
                r = await ex.fetch_funding_rate_history(sym, since=since, limit=100)
                if not r:
                    break
                rows += [(x["timestamp"], float(x["fundingRate"])) for x in r]
                nxt = r[-1]["timestamp"] + 1
                if nxt <= since or len(r) < 100:
                    break
                since = nxt
                await asyncio.sleep(0.12)
            if rows:
                json.dump(rows, open(path, "w"))
                ok += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            print(f"    {name} 실패: {str(e)[:70]}", flush=True)
        if n % 10 == 0:
            print(f"    [{n}/{len(syms)}] 성공 {ok} 실패 {fail}", flush=True)
    await ex.close()
    print(f"  완료 — 성공 {ok} · 실패 {fail}")


asyncio.run(main())
