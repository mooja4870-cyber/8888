#!/usr/bin/env python3
"""
lab_data.py — 전략 실험용 90일 시세 캐시

같은 데이터를 여러 전략이 반복해서 쓰므로, 거래소에서 한 번만 받아 디스크에 캐시한다.
(거래소 호출이 전체 실험 시간의 대부분을 차지한다)

원칙
────
* 실거래에서 주문이 거부되는 종목(바이낸스 TradFi Perps)은 제외한다.
  약관 미동의 계정에서 -4411로 전량 거부되므로, 포함하면 매매할 수 없는 종목으로
  성적을 매기게 된다.
* 개발/봉인 구간 분리는 소비하는 쪽에서 한다. 여기서는 원본만 저장한다.

사용
────
    python3 lab_data.py [거래소] [타임프레임] [일수] [심볼수]
    예) python3 lab_data.py binance 15m 90 15
"""
import asyncio
import json
import os
import sys
import time

CACHE_DIR = "/Users/l/project/8888/lab_cache"
MIN_PER_TF = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


async def fetch_paged(ex, sym, tf, want):
    """페이지 크기를 가정하지 않고(바이낸스 1000 / OKX 300) 진행이 멈출 때만 종료."""
    ms = MIN_PER_TF[tf] * 60 * 1000
    since = int(time.time() * 1000) - want * ms
    out, guard = [], 0
    while len(out) < want and guard < 60:
        guard += 1
        try:
            b = await ex.fetch_ohlcv(sym, tf, since=since, limit=1000)
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
    exch = sys.argv[1] if len(sys.argv) > 1 else "binance"
    tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 90
    nsym = int(sys.argv[4]) if len(sys.argv) > 4 else 15

    base = "/Users/l/project/8408" if exch == "binance" else "/Users/l/project/8401"
    os.chdir(base)
    sys.path.insert(0, base)
    from dotenv import load_dotenv
    load_dotenv(override=True)
    try:
        from core.api_keys import load_api_keys
        load_api_keys(override=True)
    except Exception:
        pass
    from core.exchange import OKXClient

    if exch == "binance":
        key, sec, pw = os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", ""), ""
    else:
        key, sec, pw = os.getenv("OKX_API_KEY", ""), os.getenv("OKX_SECRET_KEY", ""), os.getenv("OKX_PASSPHRASE", "")

    c = OKXClient(key, sec, pw)
    await c.load_markets()
    tick = await c.get_tickers()
    mk = c.exchange.markets

    def tradable(s):
        info = (mk.get(s) or {}).get("info") or {}
        return not (info.get("contractType") == "TRADIFI_PERPETUAL"
                    or info.get("underlyingType") == "EQUITY")

    syms = [s for s in tick if s.endswith("/USDT:USDT") and tradable(s)]
    syms = sorted(syms, key=lambda s: tick[s].get("volume", 0) or 0, reverse=True)[:nsym]

    want = int(days * 24 * 60 / MIN_PER_TF[tf])
    os.makedirs(CACHE_DIR, exist_ok=True)
    print(f"  {exch} · {tf} · 목표 {days}일({want}봉) · {len(syms)}종목", flush=True)

    saved = 0
    for s in syms:
        raw = await fetch_paged(c.exchange, s, tf, want)
        if len(raw) < want * 0.8:
            print(f"    {s.split('/')[0]:<12} {len(raw)}봉 — 부족, 제외", flush=True)
            continue
        path = os.path.join(CACHE_DIR, f"{exch}_{tf}_{s.replace('/', '_').replace(':', '-')}.json")
        with open(path, "w") as f:
            json.dump(raw, f)
        d0 = time.strftime("%m-%d", time.localtime(raw[0][0] / 1000))
        d1 = time.strftime("%m-%d", time.localtime(raw[-1][0] / 1000))
        print(f"    {s.split('/')[0]:<12} {len(raw):>5}봉 {d0}~{d1} 저장", flush=True)
        saved += 1

    await c.exchange.close()
    print(f"  완료: {saved}종목 캐시 → {CACHE_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
