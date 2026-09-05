#!/usr/bin/env python3
"""equity_curve.py — 봇 하나의 총자산 추이를 **거래소 원장**에서 복원한다.

왜 원장인가
  · `snapshots.json`은 봇별 자산을 갖고 있으나 48행(약 1일)뿐이라 6일을 못 덮는다.
  · `asset_history.json`은 함대 합계라 봇별로 못 쪼갠다.
  · 거래이력 CSV는 저가 코인에서 손익 부호가 뒤집힌다(exchange_pnl.py 참조).
  → 바이낸스 fapiPrivateGetIncome은 REALIZED_PNL·COMMISSION·FUNDING_FEE·TRANSFER를
    체결 시각과 함께 준다. 현재 잔고에서 거꾸로 빼면 시점별 잔고가 정확히 복원된다.

복원식
  equity(t) = 현재잔고 − Σ(t 이후의 모든 income)
  income에는 입출금(TRANSFER)도 들어가므로, 자산 증감 중 **매매로 번 몫**과
  **돈을 넣은 몫**을 갈라서 같이 표시한다. 안 그러면 이체를 수익으로 오인한다.

봇마다 core 패키지가 달라 반드시 봇당 별도 프로세스로 돌린다.
읽기 전용 — 주문·설정·파일을 일절 건드리지 않는다.
"""
import asyncio, json, os, sys, time

BOT = sys.argv[1] if len(sys.argv) > 1 else "8407"
DAYS = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0
d = f"/Users/l/project/{BOT}"
sys.path.insert(0, d)
os.chdir(d)
from dotenv import load_dotenv
load_dotenv(os.path.join(d, ".env"), override=False)
from core.api_keys import load_api_keys
load_api_keys(override=True)

MAX_PAGES = 60


async def bnc_income_since(ex, since):
    out, seen, start = [], set(), int(since)
    for _ in range(MAX_PAGES):
        rows = await ex.fapiPrivateGetIncome({"startTime": start, "limit": 1000})
        if not rows:
            break
        new = 0
        for x in rows:
            k = (x.get("tranId"), x.get("time"), x.get("incomeType"), x.get("income"))
            if k in seen:
                continue
            seen.add(k); out.append(x); new += 1
        if len(rows) < 1000:
            break
        start = max(int(x.get("time") or 0) for x in rows) + 1
        if new == 0:
            break
    return sorted(out, key=lambda x: int(x.get("time") or 0))


async def main():
    from core.exchange import BinanceClient as C
    cl = C(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", ""))
    await cl.load_markets()
    ex = cl.exchange

    since = int((time.time() - DAYS * 86400) * 1000)
    inc = await bnc_income_since(ex, since)
    b = await ex.fetch_balance()
    total = float((b.get("USDT") or {}).get("total") or 0)
    pos = [p for p in await ex.fetch_positions() if float(p.get("contracts") or 0) != 0]
    unreal = sum(float(p.get("unrealizedPnl") or 0) for p in pos)
    await ex.close()

    # 현재 잔고에서 거꾸로 되짚어 시점별 잔고를 만든다
    events = [dict(t=int(x["time"]), ty=x.get("incomeType"), v=float(x.get("income") or 0),
                   sym=x.get("symbol") or "") for x in inc]
    cum = 0.0
    for e in events:
        cum += e["v"]
    start_eq = total - unreal - cum          # 구간 시작 시점의 실현 잔고

    curve, eq = [], start_eq
    curve.append(dict(t=since, eq=eq, ty="START", v=0.0, sym=""))
    for e in events:
        eq += e["v"]
        curve.append(dict(t=e["t"], eq=eq, ty=e["ty"], v=e["v"], sym=e["sym"]))
    curve.append(dict(t=int(time.time() * 1000), eq=total, ty="NOW", v=unreal, sym=""))

    print("JSON" + json.dumps(dict(
        bot=BOT, days=DAYS, start_eq=start_eq, total=total, unreal=unreal,
        n_events=len(events), curve=curve)))


asyncio.run(main())
