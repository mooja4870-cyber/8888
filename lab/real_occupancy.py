#!/usr/bin/env python3
"""real_occupancy.py — 백테스트 말고 **실제로** 자리가 얼마나 차 있었나.

왜 필요한가
  gap_decomposition은 모형이다. "당일청산이면 무포지션 326일"은 가정 위의 숫자다.
  그 가정이 맞는지는 **거래소 체결 이력**으로만 확인할 수 있다.

재는 법
  체결을 시간순으로 훑으며 보유 종목 수를 누적한다.
    · fillPnl == 0  → 진입 (보유 +1)
    · fillPnl != 0  → 청산 (보유 −1)
  분 단위로 쪼개 '보유 0인 시간'의 비율을 낸다. 이게 실측 무포지션 비율이다.

한계
  · 부분청산이 있으면 한 포지션이 여러 체결로 쪼개진다. ordId로 묶어 보정한다.
  · 조회 구간 시작 시점에 이미 들고 있던 포지션은 진입 기록이 없어 빠진다.
    → 그만큼 **보유율이 과소평가**된다(무포지션이 실제보다 길게 나온다).
"""
import asyncio
import datetime as dt
import json
import os
import re
import sys

import ccxt.async_support as ccxt

BOT = sys.argv[1] if len(sys.argv) > 1 else "8401"
BASE = f"/Users/l/project/{BOT}"
KEYRE = re.compile(r'^"?([A-Za-z0-9_]+)"?\s*[:=]\s*"?(.*?)"?\s*$')


def load_keys():
    """봇 모듈을 import하지 않는다 — 모듈 캐시가 남의 봇 값을 물고 온다."""
    k = {}
    for p in (f"{BASE}/.env", f"{BASE}/api.md"):
        if os.path.exists(p):
            for ln in open(p, encoding="utf-8", errors="ignore"):
                m = KEYRE.match(ln.strip())
                if m and m.group(2):
                    k[m.group(1).lower()] = m.group(2)
    return k


async def main():
    cfg = json.load(open(f"{BASE}/config.json", encoding="utf-8"))
    venue = (cfg.get("EXCHANGE_ID") or "okx").lower()
    k = load_keys()
    st = json.load(open(f"{BASE}/data/stats.json"))
    ps = st.get("perf_start_time")
    start = dt.datetime.strptime(ps, "%Y-%m-%d %H:%M:%S") if ps else \
        dt.datetime.now() - dt.timedelta(days=14)
    since = int(start.timestamp() * 1000)

    if venue == "okx":
        ex = ccxt.okx({"apiKey": k.get("apikey", ""), "secret": k.get("secretkey", ""),
                       "password": k.get("passphrase", ""), "enableRateLimit": True,
                       "options": {"defaultType": "swap"}})
    else:
        ex = ccxt.binance({"apiKey": k.get("apikey", ""), "secret": k.get("secretkey", ""),
                           "enableRateLimit": True, "options": {"defaultType": "future"}})

    ev = []          # (ts, symbol, ordId, is_exit)
    try:
        await ex.load_markets()
        if venue == "okx":
            got, end = {}, None
            for _ in range(20):
                p = {"instType": "SWAP", "limit": "100"}
                if end:
                    p["end"] = str(end)
                d = (await ex.privateGetTradeFillsHistory(p)).get("data", [])
                if not d:
                    break
                for x in d:
                    got[x["tradeId"]] = x
                o = min(int(x["ts"]) for x in d)
                if o < since or len(d) < 100:
                    break
                end = o - 1
            for x in got.values():
                t = int(x["ts"])
                if t < since:
                    continue
                ev.append((t, x["instId"], x.get("ordId", ""),
                           float(x.get("fillPnl") or 0) != 0))
        else:
            syms = cfg.get("SYMBOL_WHITELIST") or []
            for s in syms:
                cur = since
                for _ in range(6):     # 6일씩 끊어 받는다(7일 조용한 절단 회피)
                    try:
                        tr = await ex.fetch_my_trades(s, since=cur, limit=1000)
                    except Exception:
                        break
                    if not tr:
                        break
                    for t in tr:
                        info = t.get("info") or {}
                        ev.append((t["timestamp"], s, str(info.get("orderId", "")),
                                   float(info.get("realizedPnl") or 0) != 0))
                    nxt = max(t["timestamp"] for t in tr) + 1
                    if nxt <= cur or len(tr) < 1000:
                        break
                    cur = nxt
    finally:
        await ex.close()

    if not ev:
        print(f"  {BOT}: 체결 없음 (조회 시작 {start:%Y-%m-%d %H:%M})")
        return

    ev.sort()
    # ordId로 묶어 부분청산을 한 건으로 본다
    seen_entry, seen_exit = set(), set()
    steps = []
    for t, sym, oid, is_exit in ev:
        key = (sym, oid)
        if is_exit:
            if key in seen_exit:
                continue
            seen_exit.add(key)
            steps.append((t, -1))
        else:
            if key in seen_entry:
                continue
            seen_entry.add(key)
            steps.append((t, +1))

    now = int(dt.datetime.now().timestamp() * 1000)
    held, prev, idle_ms, total_ms = 0, steps[0][0], 0, 0
    peak = 0
    for t, d in steps:
        span = t - prev
        total_ms += span
        if held <= 0:
            idle_ms += span
        held = max(0, held + d)
        peak = max(peak, held)
        prev = t
    span = now - prev
    total_ms += span
    if held <= 0:
        idle_ms += span

    days = total_ms / 86400000
    idle_d = idle_ms / 86400000
    maxpos = int(cfg.get("MAX_POSITIONS", 3))
    print(f"\n  {BOT} ({venue.upper()}) — 실거래 보유율   "
          f"{start:%Y-%m-%d %H:%M} ~ 현재 ({days:.1f}일)")
    print(f"    체결 {len(ev)}건 · 진입 {len(seen_entry)}건 · 청산 {len(seen_exit)}건 "
          f"· 최대 동시보유 {peak}/{maxpos}")
    print(f"    ▶ 무포지션 {idle_d:.1f}일 ({idle_ms / total_ms * 100:.0f}%) "
          f"· 보유율 {(1 - idle_ms / total_ms) * 100:.0f}%")
    print(f"    (조회 시작 시점에 이미 보유 중이던 포지션은 빠지므로 보유율은 과소평가)")


if __name__ == "__main__":
    asyncio.run(main())
