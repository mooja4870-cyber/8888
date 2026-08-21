#!/usr/bin/env python3
"""collect_4h_all.py — OKX USDT 무기한 전 종목 4시간봉 (상장일 이분탐색 후 순방향 수집)

두 번 틀렸다. 기록해 둔다.
────────────────────────
1차 `since=3년전` 고정 → 434종목 중 88개만. **OKX는 `since`가 상장 이전이면 0건**을
   돌려준다(상장일로 잘라주지 않음). 그래서 신규 상장 종목이 전부 빠졌다.
2차 거꾸로(`after`) 페이지네이션 → 244종목이나 대부분 **정확히 1440봉(240일)에서 잘림**.
   실측: WLD는 `since=1000일전`이면 2023-11-22부터 나오는데 거꾸로는 240일치만 받았다.
   즉 거꾸로 받기는 API가 제공하는 범위보다 훨씬 적게 준다.

3차(이 파일) — 종목마다 **상장일을 이분탐색**으로 찾고, 거기서부터 순방향으로 받는다.
   `since`를 넣었을 때 자료가 나오는 가장 이른 지점이 상장일이다.
   실측 확인: 2Z는 400일 전 0건 / 300일 전 300건 → 상장은 그 사이.

왜 이렇게까지 하나
─────────────────
이동평균 20/100이 탐색 구간에서 월 +5.2%(2.9σ)였는데 최종확인 구간(최근 6개월)이
22건뿐이라 판정 불가였다(월 −0.0%). 종목이 늘면 그 구간 표본이 늘어 판정이 된다.
**돈을 넣기 전에 최종확인을 통과해야 한다.**
"""
import json, os, sys, time

BOT = "/Users/l/project/8401"
OUT = "/Users/l/project/8888/lab_cache_4h_all"
TF, STEP_MS = "4h", 4 * 3600 * 1000
MIN_BARS = 1200           # 200일 하한
MAX_PAGES = 40

sys.path.insert(0, BOT)
os.chdir(BOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(BOT, ".env"), override=False)
from core.api_keys import load_api_keys
load_api_keys(override=True)

import asyncio


async def find_start(ex, sym, now):
    """자료가 나오는 가장 이른 since를 이분탐색. 반환 ms 또는 None."""
    lo, hi = 100, 2200            # 일 단위. hi가 클수록 과거
    async def has(days):
        r = await ex.fetch_ohlcv(sym, TF, since=int((now - days * 86400) * 1000), limit=10)
        await asyncio.sleep(0.06)
        return bool(r), (r[0][0] if r else None)
    ok, _ = await has(lo)
    if not ok:
        return None                # 100일도 안 되면 버린다
    ok_hi, ts_hi = await has(hi)
    if ok_hi:
        return int((now - hi * 86400) * 1000)
    for _ in range(9):             # 2^9 = 512 → 일 단위까지 좁혀짐
        mid = (lo + hi) // 2
        ok_mid, _ = await has(mid)
        if ok_mid:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 3:
            break
    return int((now - lo * 86400) * 1000)


async def fetch_forward(ex, sym, since):
    rows = []
    for _ in range(MAX_PAGES):
        r = await ex.fetch_ohlcv(sym, TF, since=since, limit=300)
        if not r:
            break
        rows += r
        nxt = r[-1][0] + STEP_MS
        if nxt <= since or len(r) < 300:
            break
        since = nxt
        await asyncio.sleep(0.08)
    seen, clean = set(), []
    for x in rows:
        if x[0] not in seen:
            seen.add(x[0])
            clean.append(x)
    clean.sort(key=lambda x: x[0])
    return clean


async def main():
    from core.exchange import OKXClient
    cl = OKXClient(os.getenv("OKX_API_KEY", ""), os.getenv("OKX_SECRET_KEY", ""),
                   os.getenv("OKX_PASSPHRASE", ""))
    await cl.load_markets()
    ex = cl.exchange
    os.makedirs(OUT, exist_ok=True)
    now = time.time()

    syms = sorted(s for s, m in ex.markets.items()
                  if m.get("swap") and m.get("quote") == "USDT" and m.get("active"))
    print(f"  USDT 무기한 {len(syms)}종목 · {TF} · 상장일 이분탐색 후 순방향", flush=True)

    ok = short = fail = 0
    for n, sym in enumerate(syms, 1):
        name = sym.split("/")[0]
        path = os.path.join(OUT, f"okx_4h_{name}.json")
        if os.path.exists(path) and len(json.load(open(path))) >= 6500:
            ok += 1                 # 3년치는 이미 제대로 받은 것
            continue
        try:
            st = await find_start(ex, sym, now)
            clean = await fetch_forward(ex, sym, st) if st else []
        except Exception as e:
            fail += 1
            print(f"    {name} 실패: {str(e)[:60]}", flush=True)
            continue
        if len(clean) < MIN_BARS:
            short += 1
            continue
        json.dump(clean, open(path, "w"))
        ok += 1
        if n % 40 == 0:
            print(f"    [{n}/{len(syms)}] 확보 {ok} · 짧음 {short} · 실패 {fail}", flush=True)
    await ex.close()
    files = [f for f in os.listdir(OUT) if f.endswith(".json")]
    print(f"  완료 — 확보 {len(files)}종목 · 이력부족 {short} · 실패 {fail}")


asyncio.run(main())
