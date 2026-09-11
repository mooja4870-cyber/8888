#!/usr/bin/env python3
"""sltp_backtest.py — 실제 진입 지점에 다른 손익폭을 소급 적용해 비교한다.

왜 이 방식인가
  신호 생성 로직을 재현하면 오차가 들어간다. 대신 **거래소 원장의 실제 진입
  시각·종목·방향·진입가**를 그대로 쓰고, 그 지점부터 새 SL/TP가 어디에 먼저
  닿았는지 1시간봉으로 판정한다. 진입 판단은 손대지 않고 청산 조건만 바꾼다.

한계 — 반드시 함께 볼 것
  · 손절이 넓어지면 자금이 묶여 **다음 진입을 못 하는 기회비용**이 생기는데
    이 방식은 그것을 반영하지 못한다(각 거래를 독립으로 본다).
  · 표본이 87건이라 결론은 방향 참고용이다.
  · 수수료는 왕복 0.10%로 가정한다.
"""
import os, sys, asyncio, datetime, statistics as st

BOT = sys.argv[1] if len(sys.argv) > 1 else "8401"
DAYS = float(sys.argv[2]) if len(sys.argv) > 2 else 14
FEE = 0.10          # 왕복 수수료 %
MAX_HOLD_H = 24 * 7  # 최대 보유 168시간

d = f"/Users/l/project/{BOT}"; sys.path.insert(0, d); os.chdir(d)
from dotenv import load_dotenv; load_dotenv(f"{d}/.env", override=False)
from core.api_keys import load_api_keys; load_api_keys(override=True)
import ccxt.async_support as ccxt

SINCE = int((datetime.datetime.now() - datetime.timedelta(days=DAYS)).timestamp() * 1000)


async def main():
    ex = ccxt.okx({'apiKey': os.getenv("OKX_API_KEY", ""), 'secret': os.getenv("OKX_SECRET_KEY", ""),
                   'password': os.getenv("OKX_PASSPHRASE", ""), 'enableRateLimit': True,
                   'options': {'defaultType': 'swap'}})
    await ex.load_markets()
    rows, after = [], None
    for _ in range(30):
        q = {"instType": "SWAP", "limit": "100"}
        if after: q["after"] = after
        r = await ex.privateGetAccountPositionsHistory(q)
        dd = r.get("data", [])
        if not dd: break
        rows += dd; after = dd[-1].get("uTime")
        if len(dd) < 100 or int(dd[-1].get("uTime", 0)) < SINCE: break

    trades = []
    for x in rows:
        try:
            ut = int(x.get("uTime", 0)); ct = int(x.get("cTime", 0) or ut)
            if ut < SINCE: continue
            op = float(x.get("openAvgPx") or 0)
            if op <= 0: continue
            side = "short" if "short" in str(x.get("direction") or x.get("posSide") or "").lower() else "long"
            trades.append(dict(sym=x.get("instId"), ts=ct, px=op, side=side,
                               real=float(x.get("realizedPnl") or 0)))
        except Exception: pass
    trades.sort(key=lambda t: t["ts"])
    print(f"{BOT} · 최근 {DAYS:.0f}일 · 실제 진입 {len(trades)}건\n")

    # 종목별 1시간봉 한 번만 수집
    ohlcv = {}
    for sym in sorted({t["sym"] for t in trades}):
        try:
            o = await ex.fetch_ohlcv(sym, "1h", since=SINCE - 3600_000 * 4, limit=600)
            ohlcv[sym] = o
        except Exception:
            ohlcv[sym] = []

    def simulate(sl_pct, tp_pct, subset=None):
        """가격 기준 SL/TP. 반환: (건수, 승, 평균수익률%, 총수익률%)"""
        out = []
        for t in (subset if subset is not None else trades):
            o = ohlcv.get(t["sym"]) or []
            px = t["px"]
            if t["side"] == "long":
                sl, tp = px * (1 - sl_pct / 100), px * (1 + tp_pct / 100)
            else:
                sl, tp = px * (1 + sl_pct / 100), px * (1 - tp_pct / 100)
            hit = None
            for c in o:
                if c[0] < t["ts"]: continue
                if (c[0] - t["ts"]) / 3600_000 > MAX_HOLD_H: break
                hi, lo = c[2], c[3]
                if t["side"] == "long":
                    if lo <= sl: hit = -sl_pct; break
                    if hi >= tp: hit = +tp_pct; break
                else:
                    if hi >= sl: hit = -sl_pct; break
                    if lo <= tp: hit = +tp_pct; break
            if hit is None:
                last = o[-1][4] if o else px
                r = (last / px - 1) * 100 * (1 if t["side"] == "long" else -1)
                hit = max(-sl_pct, min(tp_pct, r))
            out.append(hit - FEE)
        n = len(out); w = sum(1 for x in out if x > 0)
        return n, w, (sum(out) / n if n else 0), sum(out)

    # [강건성] 기간을 반으로 갈라 두 구간 모두에서 같은 방향인지 본다.
    half = len(trades)//2
    A, B = trades[:half], trades[half:]
    print(f"  {'SL':>6} {'TP':>6} {'RR':>5} {'전체건당':>9} {'전반건당':>9} {'후반건당':>9} {'일관성':>8}")
    combos = [(1.44, 2.76), (2.5, 5.0), (3.0, 6.0), (4.0, 8.0),
              (5.0, 10.0), (6.0, 12.0), (7.0, 14.0), (7.0, 21.0), (10.0, 20.0)]
    for sl, tp in combos:
        _, _, avg, _ = simulate(sl, tp)
        _, _, a, _ = simulate(sl, tp, A)
        _, _, b, _ = simulate(sl, tp, B)
        same = "✅ 동일" if (a > 0) == (b > 0) else "❌ 엇갈림"
        print(f"  {sl:5.1f}% {tp:5.1f}% {tp/sl:5.2f} {avg:+9.3f} {a:+9.3f} {b:+9.3f} {same:>8}")
    await ex.close()

asyncio.run(main())
