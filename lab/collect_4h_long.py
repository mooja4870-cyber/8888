#!/usr/bin/env python3
"""collect_4h_long.py — 4시간봉 장기 데이터 수집 (표본 확대용)

왜 필요한가
──────────
48조합 전수 검색에서 살아남은 건 4시간봉 추세 계열 3개뿐인데, 표본이 76~169건이라
오차가 값만큼 크다(+0.566±0.514 등). 통계적으로 0과 구분되지 않는다.
그리고 48조합을 돌렸으니 우연히 2~3개가 양쪽 플러스로 나오는 건 정상이다.

표본을 늘리는 것 말고는 가릴 방법이 없다.
  · 기간 180일 → **3년** (표본 6배)
  · 종목 61개 → **가능한 전부** (표본 2배 이상)
합치면 오차가 1/3~1/4로 줄어 진짜 엣지인지 우연인지 갈린다.

4시간봉은 15분봉의 1/16 크기라 3년치도 종목당 6570봉뿐이다. 수집이 가볍다.
"""
import json, os, sys, time

BOT = "/Users/l/project/8401"
OUT = "/Users/l/project/8888/lab_cache_4h_3y"
YEARS = 3
TF = "4h"
MIN_BARS = 2000          # 이보다 짧으면 검증에 못 쓴다(약 1년)

sys.path.insert(0, BOT)
os.chdir(BOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(BOT, ".env"), override=False)
from core.api_keys import load_api_keys
load_api_keys(override=True)

import asyncio


async def main():
    from core.exchange import OKXClient
    cl = OKXClient(os.getenv("OKX_API_KEY", ""), os.getenv("OKX_SECRET_KEY", ""),
                   os.getenv("OKX_PASSPHRASE", ""))
    await cl.load_markets()
    ex = cl.exchange
    os.makedirs(OUT, exist_ok=True)

    syms = [s for s, m in ex.markets.items()
            if m.get("swap") and m.get("quote") == "USDT" and m.get("active")]
    syms.sort()
    print(f"  USDT 무기한 {len(syms)}종목 · {TF} · 최대 {YEARS}년", flush=True)

    start = int((time.time() - YEARS * 365 * 86400) * 1000)
    step = 4 * 3600 * 1000
    ok = short = fail = 0
    for n, sym in enumerate(syms, 1):
        name = sym.split("/")[0]
        path = os.path.join(OUT, f"okx_4h_{name}.json")
        if os.path.exists(path):
            ok += 1
            continue
        rows, since = [], start
        try:
            while True:
                r = await ex.fetch_ohlcv(sym, TF, since=since, limit=300)
                if not r:
                    break
                rows += r
                nxt = r[-1][0] + step
                if nxt <= since or len(r) < 300:
                    break
                since = nxt
                await asyncio.sleep(0.1)
        except Exception as e:
            fail += 1
            print(f"    {name} 실패: {str(e)[:60]}", flush=True)
            continue
        # 중복 제거 후 저장
        seen, clean = set(), []
        for x in rows:
            if x[0] not in seen:
                seen.add(x[0])
                clean.append(x)
        clean.sort(key=lambda x: x[0])
        if len(clean) < MIN_BARS:
            short += 1
            continue
        json.dump(clean, open(path, "w"))
        ok += 1
        if n % 25 == 0:
            print(f"    [{n}/{len(syms)}] 확보 {ok} · 짧음 {short} · 실패 {fail}", flush=True)
    await ex.close()
    files = [f for f in os.listdir(OUT) if f.endswith(".json")]
    print(f"  완료 — 확보 {len(files)}종목 · 이력부족 {short} · 실패 {fail}")


asyncio.run(main())
