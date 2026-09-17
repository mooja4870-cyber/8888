#!/usr/bin/env python3
"""exchange_report.py — 거래소 원장 기준 함대 성과 리포트

거래이력 CSV의 `수익(USDT)`는 신뢰할 수 없다. 실측(2026-08-12 8403):
  CSV 기준  +$1.923   /  거래소 원장  **−$1.125**   → $3.05 괴리
성과 판단은 거래소가 말하는 값으로만 한다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2026-09-12 전면 수정] 종전 판에 **결과를 조용히 위조하는 버그 2건**이 있었다.

  ① 모듈 캐시 오염 — 봇마다 sys.path.insert 후 `core.exchange`를 import 했는데,
     첫 봇의 모듈이 sys.modules에 남아 **두 번째 봇부터 첫 봇의 클라이언트를 재사용**했다.
     실측: 8403 행에 8401의 잔고($10.5125)가 그대로 찍혔고, 바이낸스 봇은
     'okx' object has no attribute 'fapiPrivateGetIncome'로 죽었다.
     → 봇 모듈을 아예 import하지 않는다. .env에서 키만 읽어 ccxt를 직접 쓴다.

  ② OKX 조회 누락 — privateGetAccountPositionsHistory를 limit 100 단발로 불렀다.
     실측(8401): 이 엔드포인트는 09-08까지만 주는데 체결원장에는 09-10까지 있었다.
     **6라운드트립이 통째로 빠졌다.**
     → OKX도 **체결원장(fills)** 기준으로 바꾼다. 부분청산은 ordId로 묶어 1건으로 센다.

  ③ 함대 목록 하드코딩 — 8403·8408은 이미 함대에서 빠졌다.
     → config.json의 EXCHANGE_ID를 읽어 자동 판별한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

조회 경로
  OKX      : privateGetTradeFillsHistory  (fillPnl/fee) + privateGetAccountBills(type=8, 펀딩)
  바이낸스 : fapiPrivateGetIncome         (REALIZED_PNL / COMMISSION / FUNDING_FEE)

검산: 시드 + 실현손익 + 미실현 = 현재 총잔고 (일치해야 정상)
"""
import asyncio
import collections
import datetime as dt
import json
import os
import re
import sys

import ccxt.async_support as ccxt

ROOT = "/Users/l/project"
FLEET = sys.argv[1:] or ["8401", "8402", "8407", "8409", "8410"]


KEY_RE = re.compile(r'^"?([A-Za-z0-9_]+)"?\s*[:=]\s*"?(.*?)"?\s*$')


# api.md는 소문자 이름(apikey/secretkey/passphrase)을 쓰고 .env는 대문자
# (OKX_API_KEY 등)를 쓴다. 봇의 core/api_keys.py는 `_KEY_MAP`으로 소문자를
# 대문자에 **주입**해 .env를 덮어쓴다. 여기서도 같게 정규화해야 한다.
#
# [2026-09-17 실측] 이 정규화가 없어서 8406 리포트가 **8401 계좌**를 찍었다.
#   8406/.env  OKX_API_KEY = …b0cd13bd   ← 8401의 키가 남아 있었다
#   8406/api.md    apikey  = …29843dd0   ← 실제 8406 키
#   이름이 다르니 덮어쓰기가 일어나지 않고, make_client는 .env 쪽을 집었다.
#   그 결과 잔고가 $62.72 대신 $10.23(8401)으로 나오고 검산이 −50.06으로 깨졌다.
_ALIAS = {
    "apikey":     ("OKX_API_KEY", "BINANCE_API_KEY"),
    "secretkey":  ("OKX_SECRET_KEY", "BINANCE_SECRET_KEY"),
    "passphrase": ("OKX_PASSPHRASE", "BINANCE_PASSPHRASE"),
}


def read_keys(bot):
    """키를 **파싱만** 한다. 봇 모듈은 import하지 않는다(모듈 캐시 오염 방지).

    [2026-09-12] .env만 읽었더니 바이낸스 3봇이 -2015(Invalid API-key)로 전멸했다.
    봇의 `core/api_keys.load_api_keys()`가 **api.md를 나중에 읽어 .env를 덮어쓴다.**
    즉 실제 사용 키는 api.md다. 같은 우선순위(.env → api.md 덮어쓰기)를 그대로 따른다.
    """
    out = {}
    for p, sep_required in ((os.path.join(ROOT, bot, ".env"), True),
                            (os.path.join(ROOT, bot, "api.md"), False),
                            (os.path.join(ROOT, "api.md"), False)):
        if not os.path.exists(p):
            continue
        for ln in open(p, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            m = KEY_RE.match(ln)
            if m and m.group(2):
                name, val = m.group(1), m.group(2)
                out[name] = val
                # 소문자 별칭은 대문자 이름에도 넣어 .env의 낡은 값을 덮는다
                for up in _ALIAS.get(name.lower(), ()):
                    out[up] = val
    return out


def make_client(bot):
    cfg = json.load(open(os.path.join(ROOT, bot, "config.json"), encoding="utf-8"))
    venue = str(cfg.get("EXCHANGE_ID", "okx")).lower()
    e = read_keys(bot)
    if venue == "okx":
        ex = ccxt.okx({"apiKey": e.get("OKX_API_KEY", ""),
                       "secret": e.get("OKX_SECRET_KEY", ""),
                       "password": e.get("OKX_PASSPHRASE", ""),
                       "enableRateLimit": True,
                       "options": {"defaultType": "swap"}})
    else:
        # 봇(core/exchange.py: BinanceClient)과 **동일한 생성자**를 쓴다.
        # binanceusdm으로 바꿔 띄우면 서명은 같아도 -2015가 났다.
        ex = ccxt.binance({"apiKey": e.get("BINANCE_API_KEY", ""),
                           "secret": e.get("BINANCE_SECRET_KEY", ""),
                           "enableRateLimit": True,
                           "options": {"defaultType": "future",
                                       "adjustForTimeDifference": True}})
    return ex, venue


async def okx_ledger(ex, since):
    """체결원장 기준. 부분청산은 ordId로 묶어 1거래로 센다."""
    fills = {}
    end = None
    for _ in range(15):
        p = {"instType": "SWAP", "limit": "100"}
        if end:
            p["end"] = str(end)
        d = (await ex.privateGetTradeFillsHistory(p)).get("data") or []
        if not d:
            break
        for x in d:
            fills[x.get("tradeId") or f"{x.get('ordId')}_{x.get('ts')}"] = x
        oldest = min(int(x["ts"]) for x in d)
        if oldest < since or len(d) < 100:
            break
        end = oldest - 1

    fee = 0.0
    closes = collections.defaultdict(float)     # ordId → 청산손익 합
    for x in fills.values():
        if int(x.get("ts") or 0) < since:
            continue
        fee += abs(float(x.get("fee") or 0))
        pnl = float(x.get("fillPnl") or 0)
        if pnl != 0:
            closes[f"{x.get('instId')}|{x.get('ordId')}"] += pnl

    real = sum(closes.values())
    wins = sum(1 for v in closes.values() if v > 0)
    losses = sum(1 for v in closes.values() if v <= 0)

    fund = 0.0
    try:
        b = (await ex.privateGetAccountBills({"type": "8", "limit": "100"})).get("data") or []
        fund = sum(float(x.get("balChg") or 0) for x in b if int(x.get("ts") or 0) >= since)
    except Exception:
        pass
    # fillPnl은 수수료·펀딩 **전** 값이다. 순실현 = fillPnl − 수수료 + 펀딩
    return real - fee + fund, fee, fund, wins, losses, len(fills)


async def binance_ledger(ex, since):
    agg = collections.Counter()
    wins = losses = 0
    n = 0
    start = since
    for _ in range(15):
        inc = await ex.fapiPrivateGetIncome({"startTime": start, "limit": 1000})
        if not inc:
            break
        for x in inc:
            agg[x.get("incomeType")] += float(x.get("income") or 0)
            n += 1
            if x.get("incomeType") == "REALIZED_PNL":
                v = float(x.get("income") or 0)
                if v > 0:
                    wins += 1
                elif v < 0:
                    losses += 1
        if len(inc) < 1000:
            break
        start = max(int(x["time"]) for x in inc) + 1
    fee, fund = abs(agg["COMMISSION"]), agg["FUNDING_FEE"]
    real = agg["REALIZED_PNL"] + agg["COMMISSION"] + agg["FUNDING_FEE"]
    return real, fee, fund, wins, losses, n


async def fetch(bot):
    ex, venue = make_client(bot)
    try:
        s = json.load(open(os.path.join(ROOT, bot, "data", "stats.json"), encoding="utf-8"))
        seed = float(s.get("seed_money") or 0)
        ps = s.get("perf_start_time", "")
        since = int(dt.datetime.fromisoformat(ps).timestamp() * 1000)

        if venue == "okx":
            real, fee, fund, wins, losses, nf = await okx_ledger(ex, since)
        else:
            real, fee, fund, wins, losses, nf = await binance_ledger(ex, since)

        b = await ex.fetch_balance()
        total = float((b.get("USDT") or {}).get("total") or 0)
        pos = [p for p in await ex.fetch_positions() if float(p.get("contracts") or 0) != 0]
        unreal = sum(float(p.get("unrealizedPnl") or 0) for p in pos)
    finally:
        await ex.close()

    days = max((dt.datetime.now().timestamp() - since / 1000) / 86400.0, 1e-9)
    return dict(bot=bot, venue=venue, seed=seed, real=real, fee=fee, fund=fund,
                unreal=unreal, total=total, pos=len(pos), wins=wins, losses=losses,
                days=days, ps=ps, nfill=nf)


async def main():
    rows = []
    for bot in FLEET:
        try:
            rows.append(await fetch(bot))
        except Exception as e:
            print(f"  ❌ {bot} 조회 실패: {type(e).__name__}: {str(e)[:90]}")
    if not rows:
        return

    print(f"\n  ══ 거래소 원장(체결) 기준 함대 성과 ══   {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  {'봇':<6}{'거래소':<9}{'시드':>7}{'실현':>9}{'미실현':>8}{'총잔고':>8}"
          f"{'시드대비':>9}{'월환산':>8}{'승패':>9}{'수수료':>8}{'펀딩':>8}{'운영일':>7}")
    print("  " + "─" * 100)
    ts = tr = tu = tt = 0.0
    for r in rows:
        ret = (r["total"] - r["seed"]) / r["seed"] if r["seed"] else 0.0
        mo = ((1 + ret) ** (30 / r["days"]) - 1) * 100 if r["days"] > 0 and ret > -1 else 0.0
        ts += r["seed"]; tr += r["real"]; tu += r["unreal"]; tt += r["total"]
        wl = f"{r['wins']}승{r['losses']}패"
        print(f"  {r['bot']:<6}{r['venue']:<9}{r['seed']:>7.2f}{r['real']:>+9.4f}"
              f"{r['unreal']:>+8.4f}{r['total']:>8.2f}{ret*100:>+8.2f}%{mo:>+7.1f}%"
              f"{wl:>9}{r['fee']:>8.4f}{r['fund']:>+8.4f}{r['days']:>7.1f}")
    print("  " + "─" * 100)
    tret = (tt - ts) / ts if ts else 0.0
    print(f"  {'합계':<6}{'':<9}{ts:>7.2f}{tr:>+9.4f}{tu:>+8.4f}{tt:>8.2f}{tret*100:>+8.2f}%")

    print("\n  ── 검산 (시드 + 실현 + 미실현 = 총잔고) ──")
    for r in rows:
        calc = r["seed"] + r["real"] + r["unreal"]
        gap = r["total"] - calc
        ok = abs(gap) < 0.1
        note = "" if ok else "  ← 리셋 전 잔고 이월·입출금·조회범위 초과를 의심"
        print(f"  {r['bot']}: {calc:.4f} vs 실제 {r['total']:.4f} · 차이 {gap:+.4f} "
              f"{'✅' if ok else '⚠️'}{note}")

    print("\n  ── 건당 기대값 (표본이 작으면 아무 뜻도 없다) ──")
    for r in rows:
        n = r["wins"] + r["losses"]
        if n:
            print(f"  {r['bot']}: {n:3}건 · 건당 {r['real']/n:+.4f} USDT · "
                  f"승률 {r['wins']/n*100:4.1f}% · 수수료가 실현의 "
                  f"{abs(r['fee']/r['real'])*100 if r['real'] else 0:.0f}%"
                  + ("   ⚠️ 표본 30건 미만 — 판정 불가" if n < 30 else ""))
        else:
            print(f"  {r['bot']}:   0건 — 리셋 이후 청산 없음")
    print()


if __name__ == "__main__":
    asyncio.run(main())
