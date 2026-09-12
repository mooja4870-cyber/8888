#!/usr/bin/env python3
"""fee_anatomy.py — 수수료가 실현손익의 56~71%를 먹는 구조를 해부한다.

절감안을 설계하기 전에 **지금 무엇을 얼마에 내고 있는지**부터 잰다.
추정하지 않는다. 체결원장의 fee / fillSz / fillPx로 실효 요율을 역산한다.

낸다
  ① 실효 요율 (체결 1건당 fee ÷ 명목가) — 테이커인가 메이커인가
  ② 체결의 메이커/테이커 구성비 (OKX execType M/T · 바이낸스 maker 플래그)
  ③ 거래당 총이익(gross) vs 수수료 — **수수료를 못 넘긴 거래가 몇 %인가**
  ④ 같은 종목 반복 회전(처닝)이 수수료에서 차지하는 몫

④를 따로 보는 이유: 8401은 09-09~09-10 34시간 동안 DOT 한 종목만 6라운드트립
돌았다. 신호가 좋아서가 아니라 스위칭·재진입이 같은 자리를 반복한 것이다.
이런 회전은 **기대값이 0인데 수수료만 확정으로 나간다.**
"""
import asyncio
import collections
import datetime as dt
import json
import os
import re
import statistics as st
import sys

import ccxt.async_support as ccxt

ROOT = "/Users/l/project"
FLEET = sys.argv[1:] or ["8401", "8402", "8409", "8410"]
KEY_RE = re.compile(r'^"?([A-Za-z0-9_]+)"?\s*[:=]\s*"?(.*?)"?\s*$')


def read_keys(bot):
    """실사용 키는 api.md다(.env를 덮어쓴다). 봇 모듈은 import하지 않는다."""
    out = {}
    for p in (os.path.join(ROOT, bot, ".env"),
              os.path.join(ROOT, bot, "api.md"),
              os.path.join(ROOT, "api.md")):
        if not os.path.exists(p):
            continue
        for ln in open(p, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            m = KEY_RE.match(ln)
            if m and m.group(2):
                out[m.group(1)] = m.group(2)
    return out


def make_client(bot):
    cfg = json.load(open(os.path.join(ROOT, bot, "config.json"), encoding="utf-8"))
    venue = str(cfg.get("EXCHANGE_ID", "okx")).lower()
    e = read_keys(bot)
    if venue == "okx":
        return ccxt.okx({"apiKey": e.get("OKX_API_KEY", ""), "secret": e.get("OKX_SECRET_KEY", ""),
                         "password": e.get("OKX_PASSPHRASE", ""), "enableRateLimit": True,
                         "options": {"defaultType": "swap"}}), venue, cfg
    return ccxt.binance({"apiKey": e.get("BINANCE_API_KEY", ""),
                         "secret": e.get("BINANCE_SECRET_KEY", ""), "enableRateLimit": True,
                         "options": {"defaultType": "future",
                                     "adjustForTimeDifference": True}}), venue, cfg


async def okx_fills(ex, since):
    """체결 단위로 정규화: ts, sym, ordId, notional, fee, pnl, maker"""
    got, end = {}, None
    for _ in range(15):
        p = {"instType": "SWAP", "limit": "100"}
        if end:
            p["end"] = str(end)
        d = (await ex.privateGetTradeFillsHistory(p)).get("data") or []
        if not d:
            break
        for x in d:
            got[x.get("tradeId") or f"{x.get('ordId')}_{x.get('ts')}"] = x
        oldest = min(int(x["ts"]) for x in d)
        if oldest < since or len(d) < 100:
            break
        end = oldest - 1
    await ex.load_markets()
    out = []
    for x in got.values():
        ts = int(x.get("ts") or 0)
        if ts < since:
            continue
        inst = x.get("instId")
        sym = inst.replace("-USDT-SWAP", "/USDT:USDT")
        try:
            csz = float(ex.market(sym).get("contractSize") or 1)
        except Exception:
            csz = 1.0
        notional = float(x.get("fillSz") or 0) * csz * float(x.get("fillPx") or 0)
        out.append(dict(ts=ts, sym=inst, ordId=x.get("ordId"), notional=notional,
                        fee=abs(float(x.get("fee") or 0)), pnl=float(x.get("fillPnl") or 0),
                        maker=(x.get("execType") == "M")))
    return out


async def bnc_fills(ex, since):
    out = []
    await ex.load_markets()
    syms = sorted({m["symbol"] for m in ex.markets.values()
                   if m.get("swap") and m.get("quote") == "USDT"})
    # 전 종목 조회는 비싸다. 실제로 거래한 종목만 income에서 뽑아 좁힌다.
    inc, start = [], since
    for _ in range(10):
        r = await ex.fapiPrivateGetIncome({"startTime": start, "limit": 1000})
        if not r:
            break
        inc += r
        if len(r) < 1000:
            break
        start = max(int(x["time"]) for x in r) + 1
    traded = sorted({x.get("symbol") for x in inc if x.get("symbol")})

    # [2026-09-12] 바이낸스 userTrades는 **조회 범위 7일 상한**이 있다. since만 주고
    # 11일치를 부르면 오류 없이 **일부만 돌려준다**(실측 8410: DOT 0건·BNB 1건만 오고
    # AR은 부호가 뒤집혔다 — income −0.2592 vs trades +0.4818). 조용한 실패다.
    # 반드시 6일 창으로 쪼개 이어붙인다. 검산은 income REALIZED_PNL 합과 맞춘다.
    WIN = 6 * 86400_000
    now = int(dt.datetime.now().timestamp() * 1000)
    for raw in traded:
        sym = next((s for s in syms if ex.market(s)["id"] == raw), None)
        if not sym:
            continue
        seen = {}
        cur = since
        while cur < now:
            end = min(cur + WIN, now)
            try:
                tr = await ex.fetch_my_trades(sym, since=cur, limit=1000,
                                              params={"endTime": end})
            except Exception:
                tr = []
            for t in tr:
                seen[str((t.get("info") or {}).get("id") or t.get("id"))] = t
            cur = end + 1
        for t in seen.values():
            info = t.get("info") or {}
            out.append(dict(ts=int(t["timestamp"]), sym=raw, ordId=str(info.get("orderId")),
                            notional=float(info.get("quoteQty") or 0),
                            fee=abs(float(info.get("commission") or 0)),
                            pnl=float(info.get("realizedPnl") or 0),
                            maker=(str(info.get("maker")).lower() == "true")))

    # 검산 — 체결 합이 income REALIZED_PNL과 맞는지 본다. 어긋나면 크게 경고한다.
    inc_rp = sum(float(x.get("income") or 0) for x in inc
                 if x.get("incomeType") == "REALIZED_PNL")
    got_rp = sum(f["pnl"] for f in out)
    if abs(got_rp - inc_rp) > 0.005:
        print(f"  ⚠️  체결원장 검산 실패: 체결합 {got_rp:+.4f} vs income {inc_rp:+.4f} "
              f"(차이 {got_rp-inc_rp:+.4f}) — 아래 수치를 믿지 말 것")
    return out


def analyse(bot, fills, seed):
    print(f"\n{'='*92}\n  {bot}   체결 {len(fills)}건\n{'='*92}")
    if not fills:
        print("  체결 없음")
        return None

    fee_tot = sum(f["fee"] for f in fills)
    not_tot = sum(f["notional"] for f in fills)
    rate = fee_tot / not_tot if not_tot else 0
    mk = [f for f in fills if f["maker"]]
    print(f"  ① 실효 요율   수수료 {fee_tot:.4f} ÷ 명목가 합 {not_tot:,.2f} = "
          f"**{rate*100:.4f}% / 체결**")
    print(f"     체결당 평균 명목가 ${not_tot/len(fills):.2f} · 평균 수수료 ${fee_tot/len(fills):.5f}")
    print(f"  ② 메이커 비중 {len(mk)}/{len(fills)}건 ({len(mk)/len(fills)*100:.1f}%)"
          + ("  → 사실상 전량 테이커" if len(mk) / len(fills) < 0.05 else ""))

    # 거래(ordId 묶음) 단위로 청산 손익 집계
    closes = collections.defaultdict(lambda: dict(pnl=0.0, fee=0.0, sym="", ts=0))
    entry_fee = collections.defaultdict(float)
    for f in fills:
        if f["pnl"] != 0:
            k = f"{f['sym']}|{f['ordId']}"
            closes[k]["pnl"] += f["pnl"]
            closes[k]["fee"] += f["fee"]
            closes[k]["sym"] = f["sym"]
            closes[k]["ts"] = max(closes[k]["ts"], f["ts"])
        else:
            entry_fee[f["sym"]] += f["fee"]

    n = len(closes)
    if not n:
        print("  청산 거래 없음")
        return None
    # 진입 수수료를 종목별로 균등 배분해 거래당 총비용을 만든다
    per_sym = collections.Counter(v["sym"] for v in closes.values())
    rows = []
    for v in closes.values():
        ef = entry_fee.get(v["sym"], 0.0) / max(per_sym[v["sym"]], 1)
        cost = v["fee"] + ef
        rows.append((v["ts"], v["sym"], v["pnl"], cost, v["pnl"] - cost))
    rows.sort()

    gross = sum(r[2] for r in rows)
    cost = sum(r[3] for r in rows)
    net = gross - cost
    under = [r for r in rows if r[2] <= r[3]]          # 총이익이 비용을 못 넘은 거래
    print(f"\n  ③ 거래 {n}건 (부분청산은 ordId로 묶음)")
    print(f"     총이익(수수료 전) {gross:+.4f} · 비용 {cost:.4f} · 순실현 {net:+.4f}")
    print(f"     **비용을 못 넘긴 거래 {len(under)}건 ({len(under)/n*100:.1f}%)**")
    print(f"     거래당 총이익 중앙값 {st.median(r[2] for r in rows):+.4f} · "
          f"거래당 비용 중앙값 {st.median(r[3] for r in rows):.4f}")

    # ④ 같은 종목 반복 회전
    sym_n = collections.Counter(r[1] for r in rows)
    churn = {s: c for s, c in sym_n.items() if c >= 4}
    ch_rows = [r for r in rows if r[1] in churn]
    print(f"\n  ④ 종목 편중 — 거래 {len(sym_n)}종목 · 상위 3종목이 "
          f"{sum(c for _, c in sym_n.most_common(3))}/{n}건 "
          f"({sum(c for _, c in sym_n.most_common(3))/n*100:.0f}%)")
    for s, c in sym_n.most_common(3):
        sub = [r for r in rows if r[1] == s]
        print(f"     {s:22} {c:3}건 · 총이익 {sum(x[2] for x in sub):+.4f} · "
              f"비용 {sum(x[3] for x in sub):.4f} · 순 {sum(x[4] for x in sub):+.4f}")
    if ch_rows:
        print(f"     4회 이상 회전 종목({len(churn)}개) 합계: {len(ch_rows)}건 · "
              f"순 {sum(r[4] for r in ch_rows):+.4f} · 비용 {sum(r[3] for r in ch_rows):.4f}")

    # 절감 시뮬레이션 (요율만 바꾼다 — 체결 여부는 별도 문제로 뒤에서 다룬다)
    print(f"\n  ⑤ 요율만 바꿨을 때 (체결은 그대로 된다고 가정 — 낙관적 상한)")
    for nm, r2 in (("현행", rate), ("메이커 0.020%", 0.0002), ("메이커 0.015%", 0.00015)):
        c2 = cost * (r2 / rate) if rate else cost
        print(f"     {nm:14} 비용 {c2:.4f} · 순실현 {gross-c2:+.4f} "
              f"({(gross-c2-net)/seed*100:+.2f}%p 시드대비)")
    return dict(bot=bot, n=n, gross=gross, cost=cost, net=net, rate=rate,
                under=len(under), maker=len(mk) / len(fills))


async def main():
    print(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "  수수료 구조 해부")
    res = []
    for bot in FLEET:
        ex, venue, cfg = make_client(bot)
        try:
            s = json.load(open(os.path.join(ROOT, bot, "data", "stats.json"), encoding="utf-8"))
            since = int(dt.datetime.fromisoformat(s["perf_start_time"]).timestamp() * 1000)
            seed = float(s.get("seed_money") or 10)
            fills = await (okx_fills(ex, since) if venue == "okx" else bnc_fills(ex, since))
        except Exception as e:
            print(f"\n  ❌ {bot} 실패: {type(e).__name__}: {str(e)[:90]}")
            continue
        finally:
            await ex.close()
        r = analyse(bot, fills, seed)
        if r:
            res.append(r)

    if res:
        print(f"\n{'='*92}\n  함대 요약\n{'='*92}")
        print(f"  {'봇':<6}{'거래':>6}{'실효요율':>10}{'메이커':>8}{'총이익':>10}"
              f"{'비용':>9}{'순실현':>10}{'비용못넘김':>11}")
        for r in res:
            print(f"  {r['bot']:<6}{r['n']:>6}{r['rate']*100:>9.4f}%{r['maker']*100:>7.0f}%"
                  f"{r['gross']:>+10.4f}{r['cost']:>9.4f}{r['net']:>+10.4f}"
                  f"{r['under']/r['n']*100:>10.0f}%")
        print()


if __name__ == "__main__":
    asyncio.run(main())
