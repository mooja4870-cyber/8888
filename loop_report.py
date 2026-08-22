#!/usr/bin/env python3
"""loop_report.py — 실험 상태판 자동 갱신 + 종료조건 판정 + 디스코드 보고

왜 만드나
────────
지금까지 실험에 **종료 조건이 없었다.** "며칠 뒤 보자"만 있어서 264조합을 돌리고도
멈출 지점을 몰랐다. 그리고 상태가 대화에만 있어서, 며칠 지나면 "지금 무슨 전략이지"를
매번 처음부터 조사했다.

이 파일이 그 둘을 담당한다.
  · `LOOP.md`의 자동 구역을 실측으로 갱신한다 (인수인계 노트)
  · 실험마다 **4중 종료조건**을 판정한다 — 걸리면 디스코드로 "판단 필요" 알림

**읽기 전용이다.** 봇 설정·전략·주문 어느 것도 건드리지 않는다.

4중 종료조건 (하나라도 걸리면 그 실험은 끝낸다)
  ① 검증 통과 — 짝 비교 2σ 도달 → 우세한 쪽 채택
  ② 최대 반복 — 200쌍 도달 → 2σ 미달이면 "차이 없음"으로 종결
  ③ 시간 한도 — 14일 경과 → 무조건 판정
  ④ 진전 없음 — 3일간 짝 10쌍 미만 → 표본이 안 쌓이므로 중단
"""
import json
import math
import os
import re
import subprocess
import sys
import time

BASE = "/Users/l/project"
HERE = os.path.join(BASE, "8888")
sys.path.insert(0, HERE)
os.chdir(HERE)

LOOP_MD = os.path.join(HERE, "LOOP.md")
PROGRESS = os.path.join(HERE, "loop_progress.json")   # ④ 진전 없음 판정용 이력

# 실험 정의 — (번호, 기준봇, 대조봇, 묻는 것, 시작시각)
EXPERIMENTS = [
    (1, "8401", "8402", "익절 유무",   "2026-08-21 23:33:00"),
    (2, "8401", "8404", "추종 유무",   "2026-08-21 23:33:00"),
    (3, "8409", "8408", "손절 여유",   "2026-08-21 23:52:00"),
    (4, "8401", "8409", "거래소 차이", "2026-08-21 23:33:00"),
]
MAX_PAIRS, MAX_DAYS, STALL_DAYS, STALL_MIN = 200, 14, 3, 10
PAIR_WINDOW_H = 6
VENUE = {"8401": "okx", "8402": "okx", "8403": "okx", "8404": "okx",
         "8408": "binance", "8409": "binance"}


def ledger(bot, since_str):
    """거래소 원장에서 (종목, 실현손익, 청산시각ms). 실패 시 빈 목록."""
    venue = VENUE.get(bot, "okx")
    if venue == "okx":
        call = ('r = await ex.privateGetAccountPositionsHistory({"instType":"SWAP","limit":"100"})\n'
                '    rows = [[x.get("instId",""), float(x.get("realizedPnl") or 0), int(x.get("uTime") or 0)]\n'
                '            for x in (r.get("data") or [])]')
        cls = "OKXClient"
        args = ('os.getenv("OKX_API_KEY",""), os.getenv("OKX_SECRET_KEY",""), '
                'os.getenv("OKX_PASSPHRASE","")')
    else:
        call = ('inc = await ex.fapiPrivateGetIncome({"startTime": since, "limit": 1000})\n'
                '    rows = [[x.get("symbol",""), float(x.get("income") or 0), int(x.get("time") or 0)]\n'
                '            for x in inc if x.get("incomeType") == "REALIZED_PNL"]')
        cls = "BinanceClient"
        args = 'os.getenv("BINANCE_API_KEY",""), os.getenv("BINANCE_SECRET_KEY","")'

    code = f'SINCE = {since_str!r}\n' + f'''
import asyncio, os, sys, time, json
sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv; load_dotenv()
from core.api_keys import load_api_keys; load_api_keys(override=True)
async def m():
    from core.exchange import {cls} as C
    cl = C({args})
    await cl.load_markets(); ex = cl.exchange
    since = int(time.mktime(time.strptime(SINCE, "%Y-%m-%d %H:%M:%S")) * 1000)
    {call}
    out = [x for x in rows if x[2] >= since and abs(x[1]) > 1e-9]
    print("JSON" + json.dumps(out))
    await ex.close()
asyncio.run(m())
'''
    py = os.path.join(BASE, bot, "venv", "bin", "python3")
    try:
        r = subprocess.run([py, "-c", code], cwd=os.path.join(BASE, bot),
                           capture_output=True, text=True, timeout=180)
    except Exception:
        return []
    for line in (r.stdout or "").splitlines():
        if line.startswith("JSON"):
            try:
                return json.loads(line[4:])
            except ValueError:
                return []
    return []


def norm(sym):
    """OKX 'BTC-USDT-SWAP' / 바이낸스 'BTCUSDT' → 'BTC'."""
    s = sym.replace("-USDT-SWAP", "").replace("USDT", "")
    return s.split("/")[0].strip("-")


def pair(la, lb):
    used, out = set(), []
    for sa, pa, ta in la:
        best, bi = None, None
        for i, (sb, pb, tb) in enumerate(lb):
            if i in used or norm(sb) != norm(sa):
                continue
            dt = abs(tb - ta) / 3600000.0
            if dt <= PAIR_WINDOW_H and (best is None or dt < best):
                best, bi = dt, i
        if bi is not None:
            used.add(bi)
            out.append((norm(sa), pa, lb[bi][1]))
    return out


def stat(v):
    n = len(v)
    if n < 2:
        return None
    m = sum(v) / n
    sd = (sum((x - m) ** 2 for x in v) / (n - 1)) ** 0.5
    se = sd / math.sqrt(n)
    return {"n": n, "mean": m, "sd": sd, "se": se, "sigma": m / se if se > 0 else 0}


def days_since(s):
    return (time.time() - time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))) / 86400.0


def judge(s, npairs, elapsed, prev_pairs):
    """4중 종료조건. (종료여부, 사유, 표시문자열)"""
    if s and abs(s["sigma"]) >= 2:
        win = "대조봇" if s["mean"] > 0 else "기준봇"
        return True, f"① 2σ 통과 → **{win} 우세**", "★판정"
    if npairs >= MAX_PAIRS:
        return True, f"② {MAX_PAIRS}쌍 도달 → 차이 없음으로 종결", "종결"
    if elapsed >= MAX_DAYS:
        return True, f"③ {MAX_DAYS}일 경과 → 기한 종료", "기한종료"
    if elapsed >= STALL_DAYS and prev_pairs is not None and npairs < STALL_MIN:
        return True, f"④ {STALL_DAYS}일간 {npairs}쌍뿐 → 표본 부족으로 중단", "중단"
    return False, "", "진행"


def replace_block(text, tag, body):
    pat = re.compile(rf"<!-- AUTO:{tag}:BEGIN -->.*?<!-- AUTO:{tag}:END -->", re.S)
    return pat.sub(f"<!-- AUTO:{tag}:BEGIN -->\n{body}\n<!-- AUTO:{tag}:END -->", text)


def main():
    hist = {}
    if os.path.exists(PROGRESS):
        try:
            hist = json.load(open(PROGRESS))
        except ValueError:
            hist = {}

    cache, rows, alerts = {}, [], []
    for no, ref, cmp_, q, start in EXPERIMENTS:
        for b in (ref, cmp_):
            if b not in cache:
                cache[b] = ledger(b, start)
        prs = pair(cache[ref], cache[cmp_])
        s = stat([pb - pa for _, pa, pb in prs]) if len(prs) >= 2 else None
        el = days_since(start)
        done, why, tag = judge(s, len(prs), el, hist.get(str(no)))
        sig = f"{s['sigma']:+.1f}σ" if s else "—"
        diff = f"{s['mean']:+.4f}" if s else "—"
        rows.append((no, ref, cmp_, q, len(prs), sig, diff, el, tag, why))
        if done:
            alerts.append(f"실험{no} {ref}↔{cmp_} ({q}) — {why}")
        hist[str(no)] = len(prs)

    json.dump(hist, open(PROGRESS, "w"))

    # ── LOOP.md 갱신 ──
    exp = ["| # | 대조 | 묻는 것 | 짝 | 건당차이 | σ | 경과 | 상태 |",
           "|:--|:--|:--|--:|--:|--:|--:|:--|"]
    for no, ref, cmp_, q, n, sig, diff, el, tag, _ in rows:
        exp.append(f"| {no} | {ref}↔{cmp_} | {q} | {n}/{MAX_PAIRS} | {diff} | {sig} "
                   f"| D+{el:.0f}/{MAX_DAYS} | {tag} |")

    acc = ["| 봇 | 잔고 | 청산 | 실현손익 |", "|:--|--:|--:|--:|"]
    tot = 0.0
    for b in VENUE:
        led = cache.get(b)
        if led is None:
            led = ledger(b, EXPERIMENTS[0][4])
            cache[b] = led
        pnl = sum(x[1] for x in led)
        bal = None
        try:
            import exchange_pnl
            r = exchange_pnl.get(b, max_age=600)
            bal = r.get("total") if r else None
        except Exception:
            pass
        if bal:
            tot += bal
        acc.append(f"| {b} | {f'${bal:.2f}' if bal else '—'} | {len(led)}건 | {pnl:+.4f} |")
    acc.append(f"| **합계** | **${tot:.2f}** | | |")

    nxt = ([f"- 🔔 **{a}**" for a in alerts] if alerts
           else ["- 진행 중. 종료조건에 걸린 실험 없음.",
                 f"- 다음 점검: 자동(09:00·21:00)"])

    try:
        t = open(LOOP_MD, encoding="utf-8").read()
        t = re.sub(r"\*\*최종 갱신\*\*: .*",
                   f"**최종 갱신**: {time.strftime('%Y-%m-%d %H:%M')} (loop_report 자동)", t, count=1)
        t = replace_block(t, "EXPERIMENTS", "\n".join(exp))
        t = replace_block(t, "ACCOUNTS", "\n".join(acc))
        t = replace_block(t, "NEXT", "\n".join(nxt))
        open(LOOP_MD, "w", encoding="utf-8").write(t)
        print(f"  LOOP.md 갱신 완료")
    except OSError as e:
        print(f"  LOOP.md 갱신 실패: {e}")

    print("\n".join(exp))
    print()
    print("\n".join(acc))

    # ── 종료조건 걸린 실험만 디스코드로 ──
    if alerts:
        msg = ["🔔 **[실험 종료조건 도달 — 판단 필요]**", ""] + [f"• {a}" for a in alerts]
        msg += ["", "```", *exp[2:], "```", "자세한 내용은 8888/LOOP.md"]
        try:
            from profit_guard import post_discord
            post_discord("\n".join(msg))
            print("\n  디스코드 알림 발송")
        except Exception as e:
            print(f"\n  디스코드 실패: {str(e)[:60]}")


if __name__ == "__main__":
    main()
