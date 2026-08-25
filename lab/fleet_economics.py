#!/usr/bin/env python3
"""fleet_economics.py — 6봇의 건당 경제성을 원장으로 통일 비교

왜 만드나
────────
"수익률이 마이너스"라는 말만으로는 무엇을 고쳐야 할지 알 수 없다. 원인이 셋 중 하나다.
  ① 신호에 우위가 아예 없다        → 전략을 갈아야 한다 (8409가 이랬다)
  ② 우위는 있는데 수수료가 더 크다  → 비용·회전을 줄이면 산다 (8401이 이랬다)
  ③ 표본이 적어 아직 모른다        → 판정을 미뤄야 한다

이 셋은 **건당 손익을 수수료 전/후로 갈라 bp로 환산**해야 구분된다.
금액(달러)으로 보면 봇마다 베팅 크기가 달라 비교가 안 된다.

읽는 법
  · 매매손익(bp)  = 수수료 전. **신호 자체의 힘**이다. 음수면 전략을 바꿔야 한다.
  · 수수료(bp)    = 왕복 비용. OKX·바이낸스 테이커 왕복은 약 10bp다.
  · 순손익(bp)    = 실제 결과. 이게 양수여야 돈을 번다.
  · t값           = |t|<2면 "우연과 구별되지 않는다". 표본이 더 필요하다.
  · 상위5 의존도  = 상위 5건이 매매이익에서 차지하는 비중. 100%를 크게 넘으면
                    소수 대박이 전부라는 뜻이라, 평균값을 믿으면 안 된다.

⚠️ 8403은 데이터만 읽는다. 소스는 읽지도 쓰지도 않는다(mooja 지시).
"""
import json
import math
import os
import subprocess
import sys
import time

import numpy as np

BASE = "/Users/l/project"
VENUE = {"8401": "okx", "8402": "okx", "8403": "okx", "8404": "okx",
         "8408": "binance", "8409": "binance"}
TAKER_RT = 0.000998          # 실측 왕복 수수료율(명목 환산용)


def ledger(bot, since_str):
    """[(청산ms, 순손익, 수수료, 펀딩비)] — 거래소 원장."""
    if VENUE[bot] == "okx":
        body = '''
    seen, after = {}, None
    for _ in range(60):
        pr = {"instType":"SWAP","limit":"100"}
        if after: pr["after"] = str(after)
        rr = await ex.privateGetAccountPositionsHistory(pr)
        dd = rr.get("data") or []
        if not dd: break
        for x in dd: seen[(x.get("posId"), x.get("uTime"), x.get("instId"))] = x
        oldest = min(int(x.get("uTime") or 0) for x in dd)
        if len(dd) < 100 or oldest < since: break
        after = oldest
    out = [[int(x.get("uTime") or 0), float(x.get("realizedPnl") or 0),
            float(x.get("fee") or 0), float(x.get("fundingFee") or 0)]
           for x in seen.values() if int(x.get("uTime") or 0) >= since]
'''
        cls = "OKXClient"
        args = ('os.getenv("OKX_API_KEY",""), os.getenv("OKX_SECRET_KEY",""), '
                'os.getenv("OKX_PASSPHRASE","")')
    else:
        # 바이낸스는 청산 단위 레코드가 없어 income을 시각별로 묶는다
        body = '''
    inc, seen, st = [], set(), since
    for _ in range(60):
        pg = await ex.fapiPrivateGetIncome({"startTime": st, "limit": 1000})
        if not pg: break
        fresh = 0
        for x in pg:
            k = (x.get("tranId"), x.get("symbol"), x.get("incomeType"), x.get("time"))
            if k in seen: continue
            seen.add(k); inc.append(x); fresh += 1
        if len(pg) < 1000: break
        nw = max(int(x.get("time") or 0) for x in pg)
        if nw <= st or fresh == 0: break
        st = nw
    agg = {}
    for x in inc:
        t = x.get("incomeType"); v = float(x.get("income") or 0)
        if t not in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE"): continue
        key = (x.get("symbol"), int(x.get("time") or 0))
        a = agg.setdefault(key, [0.0, 0.0, 0.0])
        if t == "REALIZED_PNL": a[0] += v
        elif t == "COMMISSION": a[1] += v
        else: a[2] += v
    out = [[k[1], v[0] + v[1] + v[2], v[1], v[2]] for k, v in agg.items() if abs(v[0]) > 1e-9]
'''
        cls = "BinanceClient"
        args = 'os.getenv("BINANCE_API_KEY",""), os.getenv("BINANCE_SECRET_KEY","")'

    code = f'SINCE_S = {since_str!r}\n' + f'''
import asyncio, os, sys, time, json
sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv; load_dotenv()
from core.api_keys import load_api_keys; load_api_keys(override=True)
async def m():
    from core.exchange import {cls} as C
    cl = C({args})
    await cl.load_markets(); ex = cl.exchange
    since = int(time.mktime(time.strptime(SINCE_S, "%Y-%m-%d %H:%M:%S")) * 1000)
{body}
    print("JSON" + json.dumps(out))
    await ex.close()
asyncio.run(m())
'''
    py = os.path.join(BASE, bot, "venv", "bin", "python3")
    try:
        r = subprocess.run([py, "-c", code], cwd=os.path.join(BASE, bot),
                           capture_output=True, text=True, timeout=300)
    except Exception:
        return []
    for line in (r.stdout or "").splitlines():
        if line.startswith("JSON"):
            try:
                return json.loads(line[4:])
            except ValueError:
                return []
    return []


def perf_start(bot):
    try:
        s = json.load(open(os.path.join(BASE, bot, "data", "stats.json"), encoding="utf-8"))
        return str(s.get("perf_start_time") or "")[:19].replace("T", " ")
    except Exception:
        return ""


def analyze(bot):
    ps = perf_start(bot) or "2026-08-01 00:00:00"
    rows = ledger(bot, ps)
    if len(rows) < 3:
        return {"bot": bot, "n": len(rows), "ps": ps}
    a = np.array(rows, dtype=float)
    net, fee, fund = a[:, 1], a[:, 2], a[:, 3]
    gross = net - fee - fund
    notl = np.abs(fee) / TAKER_RT
    ok = notl > 0
    if ok.sum() < 3:
        return {"bot": bot, "n": len(rows), "ps": ps}
    bp_net = net[ok] / notl[ok] * 10000
    bp_gr = gross[ok] / notl[ok] * 10000
    bp_fee = np.abs(fee[ok]) / notl[ok] * 10000
    t = bp_net.mean() / (bp_net.std(ddof=1) / math.sqrt(len(bp_net))) if len(bp_net) > 1 else 0.0
    g = np.sort(gross)[::-1]
    top5 = g[:5].sum() / gross.sum() * 100 if abs(gross.sum()) > 1e-9 else float("nan")
    w, l = gross[gross > 0], gross[gross < 0]
    return {"bot": bot, "n": len(rows), "ps": ps,
            "gr": bp_gr.mean(), "fee": bp_fee.mean(), "net": bp_net.mean(),
            "wr": (gross > 0).mean() * 100, "t": t, "top5": top5,
            "payoff": (w.mean() / abs(l.mean())) if len(w) and len(l) else float("nan"),
            "total": net.sum()}


def verdict(r):
    if r.get("n", 0) < 30:
        return "표본부족 — 판정불가"
    if abs(r["t"]) < 2:
        base = "통계적으로 미확정"
    else:
        base = "유의"
    if r["gr"] < 0:
        return f"① 신호에 우위 없음 → 전략교체 ({base})"
    if r["net"] < 0:
        return f"② 우위는 있으나 수수료가 더 큼 → 비용·회전 ({base})"
    return f"③ 흑자 ({base})"


def main():
    bots = sys.argv[1:] or list(VENUE)
    print("  ══ 6봇 건당 경제성 (거래소 원장 · 측정시작 이후) ══\n")
    print("  봇    청산   매매손익  수수료   순손익   승률  손익비    t값  상위5의존   총손익")
    res = []
    for b in bots:
        r = analyze(b)
        res.append(r)
        if r.get("n", 0) < 3 or "gr" not in r:
            print(f"  {b}  {r.get('n',0):>4}   ─ 표본부족 ─")
            continue
        print("  %s  %4d  %+8.2f %7.2f %+8.2f %5.1f%% %6.2f %+6.2f %8.0f%% %+8.4f" % (
            b, r["n"], r["gr"], r["fee"], r["net"], r["wr"], r["payoff"], r["t"], r["top5"], r["total"]))
    print("\n  ── 판정 ──")
    for r in res:
        if "gr" in r:
            print(f"    {r['bot']}: {verdict(r)}")
        else:
            print(f"    {r['bot']}: 표본부족 — 판정불가 ({r.get('n',0)}건)")
    print("\n  ※ bp = 명목 대비 1/10000. 수수료 10bp가 기준선(테이커 왕복)이다.")
    print("  ※ |t|<2면 우연과 구별되지 않는다 — 표본을 더 쌓기 전에는 결론 금지.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
