#!/usr/bin/env python3
"""freq_backtest.py — 거래 빈도를 줄이는 정책들을 실제 원장에 소급 적용한다.

왜 이 방식이 손익폭 백테스트보다 믿을 만한가
  손익폭을 바꾸면 "그랬다면 어디서 청산됐을까"를 **추정**해야 한다.
  빈도 제한은 다르다. 실제로 일어난 거래 중 **어느 것이 걸러졌을지**만 판정하고
  남은 거래의 **실제 실현손익을 그대로 합산**한다. 추정이 들어가지 않는다.

검증 정책
  P0  현행 (모든 거래)
  P1  동시보유 상한 N개
  P2  전역 진입 쿨다운 — 어떤 종목이든 마지막 진입 후 N시간 신규 진입 금지
  P3  종목별 재진입 금지 N시간

한계 — 반드시 함께 볼 것
  · 걸러진 거래 대신 **다른 기회를 잡았을 가능성**은 반영하지 못한다.
    따라서 결과는 "그 거래들을 안 했다면"이지 "그 정책을 썼다면"이 아니다.
  · 수수료는 실제 원장 값이 이미 반영돼 있다.
  · 전반/후반으로 갈라 **부호가 같은 정책만** 채택 후보로 본다.
"""
import os, sys, asyncio, datetime, statistics as st

BOT = sys.argv[1] if len(sys.argv) > 1 else "8401"
DAYS = float(sys.argv[2]) if len(sys.argv) > 2 else 14

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

    T = []
    for x in rows:
        ut = int(x.get("uTime", 0))
        if ut < SINCE: continue
        ct = int(x.get("cTime", 0) or ut)
        T.append(dict(sym=x.get("instId", ""), open=ct, close=ut,
                      pnl=float(x.get("realizedPnl") or 0)))
    T.sort(key=lambda t: t["open"])
    await ex.close()
    if not T:
        print("데이터 없음"); return

    span = (T[-1]["close"] - T[0]["open"]) / 86400000
    print(f"{BOT} · 최근 {DAYS:.0f}일 · 실제 거래 {len(T)}건 · {span:.1f}일 · "
          f"하루 {len(T)/span:.1f}건\n")

    def apply(policy, param, subset):
        """정책을 시간순으로 적용해 채택된 거래만 남긴다."""
        kept, open_pos, last_entry = [], [], 0
        last_sym = {}
        for t in subset:
            open_pos = [p for p in open_pos if p > t["open"]]
            if policy == "P1" and len(open_pos) >= param:
                continue
            if policy == "P2" and t["open"] - last_entry < param * 3600_000:
                continue
            if policy == "P3" and t["open"] - last_sym.get(t["sym"], 0) < param * 3600_000:
                continue
            kept.append(t); open_pos.append(t["close"])
            last_entry = t["open"]; last_sym[t["sym"]] = t["open"]
        return kept

    half = len(T) // 2
    A, B = T[:half], T[half:]

    def row(label, pol, par):
        k = apply(pol, par, T) if pol else T
        ka = apply(pol, par, A) if pol else A
        kb = apply(pol, par, B) if pol else B
        tot = sum(x["pnl"] for x in k)
        sa, sb = sum(x["pnl"] for x in ka), sum(x["pnl"] for x in kb)
        keep = len(k) / len(T) * 100
        per = tot / len(k) if k else 0
        same = "✅ 동일" if (sa > 0) == (sb > 0) else "❌ 엇갈림"
        print(f"  {label:26} {len(k):4d}건({keep:3.0f}%) {tot:+8.4f} {per:+8.4f} "
              f"{sa:+8.4f} {sb:+8.4f}  {same}")

    print(f"  {'정책':26} {'채택':>10} {'총손익':>8} {'건당':>8} {'전반':>8} {'후반':>8}  일관성")
    row("P0 현행 (전부)", None, None)
    print()
    for n in (1, 2, 3):
        row(f"P1 동시보유 {n}개 상한", "P1", n)
    print()
    for h in (1, 2, 4, 6, 12):
        row(f"P2 전역 쿨다운 {h}시간", "P2", h)
    print()
    for h in (6, 12, 24, 48):
        row(f"P3 종목 재진입금지 {h}시간", "P3", h)

asyncio.run(main())
