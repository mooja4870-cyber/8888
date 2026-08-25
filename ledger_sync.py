#!/usr/bin/env python3
"""ledger_sync.py — 봇이 놓친 청산을 거래소 원장에서 찾아 매매이력에 채워 넣는다

무엇이 문제였나
──────────────
봇은 **자기가 실행한 청산만** `data/trade_history.csv`에 적는다. 거래소에 걸어둔
SL/TP가 자동 체결한 건은 봇이 뒤늦게 "포지션이 사라졌다"고 알아채고
`[PERSIST] 오프라인 청산 감지 → 상태 삭제`로 **기록 없이** 지운다.

실측(2026-08-25, 8409 PENGU): 12:33:12에 원장에는 +0.0906 USDT 실현이 남았는데
CSV에는 진입만 있고 청산이 없었다. 그 탓에 봇 대시보드 승패에도, 8888 집계에도,
디스코드 요약(00W/00L)에도 나타나지 않았다. 8404에서도 청산 20건이 통째로 빠져 있었다.

왜 중요한가
  승패와 손익을 CSV 기준으로 집계하기로 정했다(2026-08-25 mooja 지시). 그런데 CSV가
  비어 있으면 **이긴 거래가 통계에서 사라진다.** 측정이 틀리면 어떤 전략 판단도 못 한다.
  실제로 CSV는 실패한 거래만 남기는 쪽으로 치우쳐 성과를 실제보다 나쁘게 보이게 했다.

어떻게 고치나
  봇 코드를 건드리지 않는다. 대신 **원장을 정답으로 두고 CSV를 사후 대조**해서
  빠진 청산만 덧붙인다. 워치독이 5분마다 부른다.
  · 중복 방지: (주문ID) 또는 (시각±120초, 심볼, 손익) 이 이미 있으면 건너뛴다
  · 덧붙인 행은 청산유형을 `원장보정`으로 적어 봇이 쓴 행과 구분한다
  · 가격·수량은 원장에 없으므로 0으로 둔다(승패·손익 집계는 손익 컬럼만 쓴다)

⚠️ 8403은 소스를 건드리지 않는다(mooja 지시). 이 스크립트도 8403의 **데이터 파일만**
   손대며 소스는 읽지도 쓰지도 않는다.

사용법
  python3 ledger_sync.py            전 봇 대조 + 보정 (워치독용)
  python3 ledger_sync.py --dry      대조만, 기록하지 않음
  python3 ledger_sync.py 8409       특정 봇만
"""
import csv
import json
import os
import subprocess
import sys
import time

BASE = "/Users/l/project"
HERE = os.path.join(BASE, "8888")
LOG = os.path.join(HERE, "ledger_sync.log")

VENUE = {"8401": "okx", "8402": "okx", "8403": "okx", "8404": "okx",
         "8408": "binance", "8409": "binance"}
LOOKBACK_H = 48          # 이 시간 안의 청산만 대조한다(과거 전체를 매번 훑지 않는다)
MATCH_SEC = 120          # 주문ID가 없을 때 같은 청산으로 볼 시각 오차


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def notify(msg):
    try:
        sys.path.insert(0, HERE)
        from profit_guard import post_discord
        post_discord(msg)
    except Exception as e:
        log(f"  (디스코드 알림 실패: {str(e)[:80]})")


def ledger(bot, since_ms):
    """거래소 원장에서 실현손익 이벤트. [(ms, 심볼, 손익, 주문ID)] — 실패 시 []."""
    venue = VENUE.get(bot, "okx")
    if venue == "okx":
        call = ('seen, after = {}, None\n'
                '    for _ in range(40):\n'
                '        pr = {"instType":"SWAP","limit":"100"}\n'
                '        if after: pr["after"] = str(after)\n'
                '        rr = await ex.privateGetAccountPositionsHistory(pr)\n'
                '        dd = rr.get("data") or []\n'
                '        if not dd: break\n'
                '        for x in dd:\n'
                '            seen[(x.get("posId"), x.get("uTime"), x.get("instId"))] = x\n'
                '        oldest = min(int(x.get("uTime") or 0) for x in dd)\n'
                '        if len(dd) < 100 or oldest < SINCE: break\n'
                '        after = oldest\n'
                '    rows = [[int(x.get("uTime") or 0), x.get("instId",""),\n'
                '             float(x.get("realizedPnl") or 0), str(x.get("posId") or "")]\n'
                '            for x in seen.values()]')
        cls, args = "OKXClient", ('os.getenv("OKX_API_KEY",""), os.getenv("OKX_SECRET_KEY",""), '
                                  'os.getenv("OKX_PASSPHRASE","")')
    else:
        call = ('inc, seen, st = [], set(), SINCE\n'
                '    for _ in range(40):\n'
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
                '    rows = [[int(x.get("time") or 0), x.get("symbol",""),\n'
                '             float(x.get("income") or 0), str(x.get("tradeId") or x.get("tranId") or "")]\n'
                '            for x in inc if x.get("incomeType") == "REALIZED_PNL"]')
        cls, args = "BinanceClient", 'os.getenv("BINANCE_API_KEY",""), os.getenv("BINANCE_SECRET_KEY","")'

    code = f"SINCE = {int(since_ms)}\n" + f'''
import asyncio, os, sys, json
sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv; load_dotenv()
from core.api_keys import load_api_keys; load_api_keys(override=True)
async def m():
    from core.exchange import {cls} as C
    cl = C({args})
    await cl.load_markets(); ex = cl.exchange
    {call}
    out = [r for r in rows if r[0] >= SINCE and abs(r[2]) > 1e-9]
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
    """'PENGU/USDT:USDT' · 'PENGUUSDT' · 'PENGU-USDT-SWAP' → 'PENGU'."""
    s = sym.replace("-USDT-SWAP", "").split("/")[0]
    return s[:-4] if s.endswith("USDT") and len(s) > 4 else s


def csv_exits(path):
    """CSV의 기존 청산 [(epoch, 심볼, 손익, 주문ID)]."""
    out = []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.reader(f):
                if len(r) < 7 or r[2] != "청산":
                    continue
                try:
                    ts = time.mktime(time.strptime(r[0].strip()[:19], "%Y-%m-%d %H:%M:%S"))
                    pnl = float(r[6])
                except (ValueError, IndexError):
                    continue
                oid = r[10].strip() if len(r) > 10 else ""
                out.append((ts, norm(r[1]), pnl, oid))
    except OSError:
        pass
    return out


def sync(bot, dry=False):
    path = os.path.join(BASE, bot, "data", "trade_history.csv")
    if not os.path.exists(path):
        return 0, 0.0
    # 대조 구간 = max(측정 시작 시점, 최근 LOOKBACK_H) 이후.
    # 초기화(perf_start)는 "여기서부터 새로 재겠다"는 의사표시다. 그보다 과거의 청산까지
    # 되살리면 지워둔 이력이 되살아나 초기화 의도를 뒤집는다. 그래서 경계를 둔다.
    since_ms = int((time.time() - LOOKBACK_H * 3600) * 1000)
    try:
        st = json.load(open(os.path.join(BASE, bot, "data", "stats.json"), encoding="utf-8"))
        ps = str(st.get("perf_start_time") or "")[:19].replace("T", " ")
        if ps:
            ps_ms = int(time.mktime(time.strptime(ps, "%Y-%m-%d %H:%M:%S")) * 1000)
            since_ms = max(since_ms, ps_ms)
    except Exception:
        pass
    led = ledger(bot, since_ms)
    if not led:
        return 0, 0.0
    have = csv_exits(path)
    have_oids = {o for _, _, _, o in have if o}

    # 대조는 **심볼 + 시각**으로만 한다. 손익까지 맞추려 하면 안 된다 —
    # 봇이 CSV에 적는 손익은 자체 계산이라 원장 realizedPnl과 미세하게 어긋난다
    # (수수료 포함 여부·반올림). 실측: 8401은 원장 85건·CSV 85건으로 다 기록돼 있는데
    # 손익 일치를 요구했더니 85건 전부를 '누락'으로 오판했다.
    # 짝지은 CSV 행은 소비 처리해 한 행이 두 번 매칭되지 않게 한다.
    unused = sorted(have)
    missing = []
    for ms, sym, pnl, oid in sorted(led):
        ts = ms / 1000.0
        if oid and (oid in have_oids or f"ID_{oid}" in have_oids):
            continue
        hit = None
        for i, (hts, hsym, _hp, _o) in enumerate(unused):
            if hsym == norm(sym) and abs(hts - ts) <= MATCH_SEC:
                hit = i
                break
        if hit is not None:
            unused.pop(hit)
            continue
        missing.append((ts, sym, pnl, oid))

    if not missing or dry:
        return len(missing), sum(m[2] for m in missing)

    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for ts, sym, pnl, oid in missing:
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
                        sym if "/" in sym else f"{norm(sym)}/USDT:USDT",
                        "청산", "sell" if pnl >= 0 else "sell",
                        0, 0, round(pnl, 8), 0,
                        "원장보정", "", f"ID_{oid}" if oid else "", "", 0, "순방향"])
    return len(missing), sum(m[2] for m in missing)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    bots = args or list(VENUE)

    total_n, lines = 0, []
    for bot in bots:
        try:
            n, pnl = sync(bot, dry)
        except Exception as e:
            log(f"  {bot} 대조 실패: {str(e)[:100]}")
            continue
        if n:
            total_n += n
            lines.append(f"{bot}: 누락 청산 {n}건 (손익 {pnl:+.4f})")

    if not total_n:
        log("이상 없음 — 매매이력과 원장 일치")
        return 0
    verb = "발견(기록 안 함)" if dry else "매매이력에 보정 기록"
    log(f"🧾 누락 청산 {total_n}건 {verb} — " + " · ".join(lines))
    if not dry:
        notify("🧾 **매매이력 보정** — 봇이 기록하지 못한 청산을 원장에서 찾아 채웠습니다\n"
               + "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
