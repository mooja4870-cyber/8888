#!/usr/bin/env python3
"""exchange_report.py — 거래소 원장 기준 4봇 성과 리포트

거래이력 CSV의 `수익(USDT)`는 신뢰할 수 없다. 실측(2026-08-12 8403):
  CSV 기준  +$1.923   /  거래소 원장  **−$1.125**   → $3.05 괴리
8408·8409는 $0.06 차이로 정합했으므로 CSV가 항상 틀린 건 아니지만,
성과 판단은 거래소가 말하는 값으로만 해야 한다.

조회 경로
  OKX      : privateGetAccountPositionsHistory — 청산 포지션별 realizedPnl/fee/fundingFee
  바이낸스 : fapiPrivateGetIncome — REALIZED_PNL / COMMISSION / FUNDING_FEE

검산: 시드 + 실현손익 + 미실현 = 현재 총잔고 (일치해야 정상)
"""
import asyncio, csv, json, os, sys, time, collections

BOTS = [("8401", "okx"), ("8403", "okx"), ("8408", "binance"), ("8409", "binance")]


async def fetch(bot, venue):
    d = f"/Users/l/project/{bot}"
    sys.path.insert(0, d)
    os.chdir(d)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(d, ".env"), override=False)
    from core.api_keys import load_api_keys
    load_api_keys(override=True)
    if venue == "okx":
        from core.exchange import OKXClient as C
        cl = C(os.getenv("OKX_API_KEY", ""), os.getenv("OKX_SECRET_KEY", ""), os.getenv("OKX_PASSPHRASE", ""))
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
        r = await ex.privateGetAccountPositionsHistory({"instType": "SWAP", "limit": "100"})
        for x in (r.get("data") or []):
            if int(x.get("uTime") or 0) < since:
                continue
            p = float(x.get("realizedPnl") or 0)
            real += p
            fee += float(x.get("fee") or 0)
            fund += float(x.get("fundingFee") or 0)
            wins += p > 0
            losses += p <= 0
    else:
        inc = await ex.fapiPrivateGetIncome({"startTime": since, "limit": 1000})
        agg = collections.Counter()
        for x in inc:
            agg[x.get("incomeType")] += float(x.get("income") or 0)
            if x.get("incomeType") == "REALIZED_PNL":
                v = float(x.get("income") or 0)
                if v > 0: wins += 1
                elif v < 0: losses += 1
        real = agg["REALIZED_PNL"] + agg["COMMISSION"] + agg["FUNDING_FEE"]
        fee, fund = agg["COMMISSION"], agg["FUNDING_FEE"]

    b = await ex.fetch_balance()
    total = float((b.get("USDT") or {}).get("total") or 0)
    pos = [p for p in await ex.fetch_positions() if float(p.get("contracts") or 0) != 0]
    unreal = sum(float(p.get("unrealizedPnl") or 0) for p in pos)
    await ex.close()
    days = max((time.time() - since / 1000) / 86400.0, 1e-9)
    return dict(bot=bot, seed=seed, real=real, fee=abs(fee), fund=fund, unreal=unreal,
                total=total, pos=len(pos), wins=wins, losses=losses, days=days, ps=ps)


async def main():
    rows = []
    for bot, venue in BOTS:
        try:
            rows.append(await fetch(bot, venue))
        except Exception as e:
            print(f"  {bot} 조회 실패: {str(e)[:70]}")
    print(f"\n  ══ 거래소 원장 기준 4봇 성과 ══  (기준 {rows[0]['ps']} 이후 {rows[0]['days']*24:.1f}시간)")
    print(f"  {'봇':<6}{'시드':>8}{'실현손익':>10}{'미실현':>9}{'총잔고':>9}{'시드대비':>9}"
          f"{'승패':>8}{'수수료':>9}{'펀딩':>8}")
    print("  " + "─" * 78)
    ts = tr = tu = tt = 0.0
    for r in rows:
        ret = (r["total"] - r["seed"]) / r["seed"] * 100 if r["seed"] else 0
        ts += r["seed"]; tr += r["real"]; tu += r["unreal"]; tt += r["total"]
        print(f"  {r['bot']:<6}{r['seed']:>8.2f}{r['real']:>+10.4f}{r['unreal']:>+9.4f}"
              f"{r['total']:>9.2f}{ret:>+8.2f}%{f'{r[chr(119)+chr(105)+chr(110)+chr(115)]}승{r[chr(108)+chr(111)+chr(115)+chr(115)+chr(101)+chr(115)]}패':>8}"
              f"{r['fee']:>9.4f}{r['fund']:>+8.4f}")
    print("  " + "─" * 78)
    print(f"  {'합계':<6}{ts:>8.2f}{tr:>+10.4f}{tu:>+9.4f}{tt:>9.2f}"
          f"{(tt-ts)/ts*100:>+8.2f}%")
    print("\n  ── 검산 (시드 + 실현 + 미실현 = 총잔고) ──")
    for r in rows:
        calc = r["seed"] + r["real"] + r["unreal"]
        gap = r["total"] - calc
        print(f"  {r['bot']}: {calc:.4f} vs 실제 {r['total']:.4f} · 차이 {gap:+.4f} "
              f"{'✅' if abs(gap) < 0.1 else '⚠️'}")


if __name__ == "__main__":
    asyncio.run(main())
