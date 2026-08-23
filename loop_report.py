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
# [2026-08-23] 실험1(익절 유무)은 22쌍·0.0σ에서 종료했다. 하락장 검증 결과
# "롱 전용은 세 국면 중 둘에서 잃는다"가 나와, 8402를 **숏 허용 시험대**로 돌렸다.
# 8402는 이제 8401과 ALLOW_SHORT 하나만 다르다.
EXPERIMENTS = [
    (2, "8401", "8404", "추종 유무",   "2026-08-21 23:33:00"),
    # [2026-08-23] 실험3 종료. 33쌍·−0.8σ였으나 측정 기간 내내 보호주문 결함으로
    # **일부 포지션에 손절이 아예 없어** 처치 자체가 적용되지 않았다. 게다가 8408은
    # 8403의 MA20/100으로 전략이 바뀌어 대조군이 아니게 됐다.
    (4, "8401", "8409", "거래소 차이", "2026-08-21 23:33:00"),
    (5, "8401", "8402", "숏 허용",     "2026-08-23 01:38:00"),
]

# 실험5는 짝 비교로 못 잰다. 두 봇이 겹치는 건 **롱뿐이고 그 롱은 서로 같기** 때문에
# 짝 차이가 0으로 나온다. 숏의 효과는 (a) 숏 거래 자체의 건당 손익과
# (b) 숏이 포지션 자리를 차지해 롱을 밀어낸 기회비용으로 나타난다.
# (a)는 아래 short_stat()이 직접 잰다. 종료조건도 여기에 건다.
SHORT_BOT, SHORT_START = "8402", "2026-08-23 01:38:00"
MAX_PAIRS, MAX_DAYS, STALL_DAYS, STALL_MIN = 200, 14, 3, 10
PAIR_WINDOW_H = 6
VENUE = {"8401": "okx", "8402": "okx", "8403": "okx", "8404": "okx",
         "8408": "binance", "8409": "binance"}


def ledger(bot, since_str):
    """거래소 원장에서 (종목, 실현손익, 청산시각ms, 방향). 실패 시 빈 목록.

    방향은 OKX만 채워진다(long/short). 바이낸스 income에는 방향이 없어 빈 문자열."""
    venue = VENUE.get(bot, "okx")
    if venue == "okx":
        # [2026-08-24] 한 페이지 100건 한도 제거. 8401 실측으로 42건이 잘려 있었다.
        call = ('seen, after = {}, None\n'
                '    for _ in range(60):\n'
                '        pr = {"instType":"SWAP","limit":"100"}\n'
                '        if after: pr["after"] = str(after)\n'
                '        rr = await ex.privateGetAccountPositionsHistory(pr)\n'
                '        dd = rr.get("data") or []\n'
                '        if not dd: break\n'
                '        for x in dd:\n'
                '            seen[(x.get("posId"), x.get("uTime"), x.get("instId"))] = x\n'
                '        oldest = min(int(x.get("uTime") or 0) for x in dd)\n'
                '        if len(dd) < 100 or oldest < since: break\n'
                '        after = oldest\n'
                '    rows = [[x.get("instId",""), float(x.get("realizedPnl") or 0), int(x.get("uTime") or 0),\n'
                '             x.get("direction") or x.get("posSide") or ""]\n'
                '            for x in seen.values()]')
        cls = "OKXClient"
        args = ('os.getenv("OKX_API_KEY",""), os.getenv("OKX_SECRET_KEY",""), '
                'os.getenv("OKX_PASSPHRASE","")')
    else:
        call = ('inc, seen, st = [], set(), int(since)\n'
                '    for _ in range(60):\n'
                '        pg = await ex.fapiPrivateGetIncome({"startTime": st, "limit": 1000})\n'
                '        if not pg: break\n'
                '        fresh = 0\n'
                '        for x in pg:\n'
                '            k = (x.get("tranId"), x.get("symbol"), x.get("incomeType"), x.get("time"))\n'
                '            if k in seen: continue\n'
                '            seen.add(k); inc.append(x); fresh += 1\n'
                '        if len(pg) < 1000: break\n'
                '        nw = max(int(x.get("time") or 0) for x in pg)\n'
                '        if nw <= st or fresh == 0: break\n'
                '        st = nw\n'
                '    rows = [[x.get("symbol",""), float(x.get("income") or 0), int(x.get("time") or 0), ""]\n'
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
    for sa, pa, ta, _da in la:
        best, bi = None, None
        for i, (sb, pb, tb, _db) in enumerate(lb):
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


def short_stat(led):
    """숏 거래만 골라 건당 손익. 짝 비교가 안 되는 실험5의 실제 측정치다.

    비교 기준은 0이 아니라 **같은 봇의 롱 건당 손익**이다. 숏을 켠 대가는
    "숏이 롱보다 나쁘면 자리만 빼앗은 것"이므로 둘을 나란히 본다."""
    sh = [p for _, p, _, d in led if d == "short"]
    lo = [p for _, p, _, d in led if d == "long"]
    return stat(sh), stat(lo), len(sh), len(lo)


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

    # ── 실험5 전용: 숏 성적 (짝 비교로는 안 잡히는 부분) ──
    sled = cache.get(SHORT_BOT) or ledger(SHORT_BOT, SHORT_START)
    sled = [r for r in sled if r[2] >= int(time.mktime(
        time.strptime(SHORT_START, "%Y-%m-%d %H:%M:%S")) * 1000)]
    ss, ls, nsh, nlo = short_stat(sled)
    short_lines = ["| 방향 | 건수 | 건당손익 | σ |", "|:--|--:|--:|--:|"]
    for nm, st, n in (("숏", ss, nsh), ("롱", ls, nlo)):
        if st:
            short_lines.append(f"| {nm} | {n} | {st['mean']:+.4f} | {st['sigma']:+.1f}σ |")
        else:
            short_lines.append(f"| {nm} | {n} | — | — |")
    if ss and ls:
        gap = ss["mean"] - ls["mean"]
        short_lines.append(f"| **숏−롱** | | **{gap:+.4f}** | |")
        # 숏이 롱보다 뚜렷이 나쁘면(2σ) 숏을 되돌린다
        se2 = (ss["se"] ** 2 + ls["se"] ** 2) ** 0.5
        if se2 > 0 and gap / se2 <= -2:
            alerts.append(f"실험5 {SHORT_BOT} 숏 허용 — 숏이 롱보다 {abs(gap):.4f} 나쁨(2σ) → 되돌림 검토")
        elif se2 > 0 and gap / se2 >= 2:
            alerts.append(f"실험5 {SHORT_BOT} 숏 허용 — 숏이 롱보다 {gap:+.4f} 우세(2σ) → 타 봇 확대 검토")
    if nsh + nlo >= MAX_PAIRS:
        alerts.append(f"실험5 {SHORT_BOT} — {nsh+nlo}건 도달, 판정 필요")
    if days_since(SHORT_START) >= MAX_DAYS:
        alerts.append(f"실험5 {SHORT_BOT} — {MAX_DAYS}일 경과, 판정 필요")

    nxt = ([f"- 🔔 **{a}**" for a in alerts] if alerts
           else ["- 진행 중. 종료조건에 걸린 실험 없음.",
                 f"- 다음 점검: 자동(09:00·21:00)"])

    try:
        t = open(LOOP_MD, encoding="utf-8").read()
        t = re.sub(r"\*\*최종 갱신\*\*: .*",
                   f"**최종 갱신**: {time.strftime('%Y-%m-%d %H:%M')} (loop_report 자동)", t, count=1)
        t = replace_block(t, "EXPERIMENTS", "\n".join(exp))
        t = replace_block(t, "ACCOUNTS", "\n".join(acc))
        t = replace_block(t, "SHORT", "\n".join(short_lines))
        t = replace_block(t, "NEXT", "\n".join(nxt))
        open(LOOP_MD, "w", encoding="utf-8").write(t)
        print(f"  LOOP.md 갱신 완료")
    except OSError as e:
        print(f"  LOOP.md 갱신 실패: {e}")

    print("\n".join(exp))
    print()
    print("\n".join(acc))
    print()
    print("\n".join(short_lines))

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
