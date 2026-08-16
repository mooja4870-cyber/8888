#!/usr/bin/env python3
"""collect_live_universe.py — 실거래와 같은 종목군의 시세를 모은다

문제
────
지금까지 검증은 거래대금 상위 15종목(BNB·BTC·ETH·SOL·XRP 등)으로 했는데,
실거래는 45종목에서 이뤄졌고 **겹치는 건 6개(13%)** 뿐이다.
8/11에 표본 확보를 위해 MIN_VOLUME_USDT를 300만 → 50만으로 낮춘 결과다.

실측(8403, 65건): 거래의 **80%가 거래대금 $3M 미만** 종목에서 나왔고
손실의 86%가 거기서 발생했다. 즉 **대형주로 검증하고 소형주로 매매**했다.
이번 주 일곱 번의 검증이 전부 이 불일치 위에 있었다.

그래서 실거래와 같은 조건(SCAN_TOP_N=80 · MIN_VOLUME_USDT≥$500K)으로
종목을 고르고 180일 15분봉을 받는다. 이후 검증은 이 캐시로 다시 돌린다.
"""
import asyncio, json, os, sys, time

OUT = "/Users/l/project/8888/lab_cache_live"
BOT = "/Users/l/project/8403"
TOP_N = 80
MIN_VOL = 500_000
DAYS = 180
TF = "15m"


async def fetch_paged(ex, sym, want):
    """페이지 크기를 가정하지 않는다(바이낸스 1000 / OKX 300)."""
    ms = 15 * 60 * 1000
    since = int(time.time() * 1000) - want * ms
    out, guard = [], 0
    while len(out) < want and guard < 80:
        guard += 1
        try:
            b = await ex.fetch_ohlcv(sym, TF, since=since, limit=1000)
        except Exception:
            break
        if not b:
            break
        nxt = b[-1][0] + 1
        if nxt <= since:
            break
        out += b
        since = nxt
    return out


async def main():
    sys.path.insert(0, BOT)
    os.chdir(BOT)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BOT, ".env"), override=False)
    from core.api_keys import load_api_keys
    load_api_keys(override=True)
    from core.exchange import OKXClient
    c = OKXClient(os.getenv("OKX_API_KEY", ""), os.getenv("OKX_SECRET_KEY", ""),
                  os.getenv("OKX_PASSPHRASE", ""))
    await c.load_markets()
    tick = await c.get_tickers()
    cand = []
    for s, t in tick.items():
        if not s.endswith("/USDT:USDT"):
            continue
        v = t.get("quoteVolume") or t.get("volume") or 0
        if v >= MIN_VOL:
            cand.append((v, s))
    cand.sort(reverse=True)
    syms = [s for _, s in cand[:TOP_N]]
    want = int(DAYS * 24 * 60 / 15)
    os.makedirs(OUT, exist_ok=True)
    print(f"  실거래 조건 재현: 거래대금 ≥${MIN_VOL:,} 상위 {TOP_N}종목 · {DAYS}일 {TF}", flush=True)
    print(f"  후보 {len(cand)}종목 중 {len(syms)}개 선정 "
          f"(하위 경계 ${cand[min(TOP_N,len(cand))-1][0]:,.0f})", flush=True)
    saved = 0
    for i, s in enumerate(syms, 1):
        base = s.split("/")[0]
        p = os.path.join(OUT, f"okx_15m_{base}.json")
        if os.path.exists(p):
            saved += 1
            continue
        raw = await fetch_paged(c.exchange, s, want)
        if len(raw) < want * 0.8:
            print(f"    [{i}/{len(syms)}] {base:<12} {len(raw)}봉 부족 — 제외", flush=True)
            continue
        json.dump(raw, open(p, "w"))
        saved += 1
        if i % 10 == 0:
            print(f"    [{i}/{len(syms)}] {base:<12} {len(raw)}봉 저장 (누적 {saved})", flush=True)
    await c.exchange.close()
    print(f"  완료: {saved}종목 → {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
