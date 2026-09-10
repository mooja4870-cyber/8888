#!/usr/bin/env python3
"""ledger_fix_values.py — CSV에 이미 기록된 청산의 **손익값**을 원장 실측으로 교정한다.

`ledger_reconcile.py`가 **빠진 행**을 채운다면, 이 도구는 **있는 행의 틀린 값**을 고친다.

왜 필요한가
  8407 `core/engine.py:757`은 거래소 PnL과 로컬 계산의 부호가 엇갈리면
  **거래소 실측을 버리고 로컬 계산을 기록**했다(v11.0.68에서 수정).
  로컬 진입가가 '가장 최근 진입'을 집어오는 탓에 같은 종목을 여러 번 회전하면
  값이 통째로 어긋난다.
      실측: UAI 원장 -0.1399 → CSV +7.3506 (53배)
            09-05 하루 원장 -0.6307 → CSV +15.1086
  코드는 고쳤지만 이미 쌓인 행은 그대로라 과거 성과 판정이 불가능하다.

방침
  ① 체결ID로 원장과 1:1 매칭한다. 부분 체결은 CSV가 `|`로 묶어 두므로 합산 비교한다.
  ② 매칭되지 않는 행은 **건드리지 않는다**(추정 금지).
  ③ 손익·수수료만 고친다. 시각·수량·가격은 원본을 존중한다.
  ④ 기본은 dry-run. `--apply`를 줘야 쓴다. 쓸 때는 전체 파일을 백업한다.

사용
    python3 ledger_fix_values.py 8407 --days 7
    python3 ledger_fix_values.py 8407 --days 7 --apply
"""
import argparse
import asyncio
import csv
import datetime as dt
import os
import shutil
import sys

BASE = "/Users/l/project"
TOL = 0.005          # 이 이하 차이는 반올림으로 보고 넘어간다


async def ledger_by_id(bot, since_ms):
    """체결ID → (realizedPnl, commission) 사전."""
    d = os.path.join(BASE, bot)
    sys.path.insert(0, d)
    os.chdir(d)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(d, ".env"), override=False)
    from core.api_keys import load_api_keys
    load_api_keys(override=True)
    from core.exchange import BinanceClient
    cl = BinanceClient(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", ""))
    await cl.load_markets()
    ex = cl.exchange
    syms, s = set(), since_ms
    while True:
        rows = await ex.fapiPrivateGetIncome({"startTime": s, "limit": 1000})
        if not rows:
            break
        for r in rows:
            if r["incomeType"] == "REALIZED_PNL":
                syms.add(r["symbol"])
        if len(rows) < 1000:
            break
        s = int(rows[-1]["time"]) + 1
    book = {}
    for sym in sorted(syms):
        try:
            tr = await ex.fapiPrivateGetUserTrades(
                {"symbol": sym, "startTime": since_ms, "limit": 500})
        except Exception:
            continue
        for t in tr:
            book[str(t["id"])] = (float(t.get("realizedPnl") or 0),
                                  float(t.get("commission") or 0))
    await ex.close()
    for k in list(sys.modules):
        if k.startswith("core"):
            del sys.modules[k]
    sys.path.remove(d)
    return book


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot")
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    since = int((dt.datetime.now() - dt.timedelta(days=a.days)).timestamp() * 1000)
    since_s = dt.datetime.fromtimestamp(since / 1000).strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(BASE, a.bot, "data", "trade_history.csv")

    book = await ledger_by_id(a.bot, since)
    with open(path, encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames
        rows = list(rd)

    fixed = unmatched = 0
    delta = 0.0
    samples = []
    for r in rows:
        if r.get("유형") != "청산" or r.get("시간", "") < since_s:
            continue
        # [2026-09-11] CSV가 체결ID를 float 문자열로 적은 행이 있다("775493040.0").
        # 원장은 정수 문자열이라 그대로는 매칭이 실패하고, 그 행의 틀린 값이
        # 영원히 교정되지 않는다(8407 TAO +1.0488 실측, 원장은 그 값이 아니다).
        ids = []
        for x in (r.get("체결ID") or "").split("|"):
            x = x.strip()
            if not x:
                continue
            if x.endswith(".0"):
                x = x[:-2]
            ids.append(x)
        hit = [book[i] for i in ids if i in book]
        if not hit or len(hit) != len(ids):
            unmatched += 1
            continue
        real_pnl = round(sum(h[0] for h in hit), 6)
        real_fee = round(abs(sum(h[1] for h in hit)), 6)
        try:
            cur = float(r.get("수익(USDT)") or 0)
        except ValueError:
            cur = 0.0
        if abs(cur - real_pnl) <= TOL:
            continue
        if len(samples) < 10:
            samples.append((r["시간"][5:16], r["심볼"].split("/")[0], cur, real_pnl))
        delta += real_pnl - cur
        fixed += 1
        r["수익(USDT)"] = real_pnl
        r["수수료(USDT)"] = real_fee
        # 수익률은 명목가/레버리지 기준으로 다시 낸다
        try:
            px = float(r.get("가격") or 0)
            qty = float(r.get("수량") or 0)
            lev = float(r.get("레버리지") or 3)
            margin = (px * qty) / lev if px > 0 and qty > 0 and lev > 0 else 0.0
            r["수익률(%)"] = round(real_pnl / margin * 100, 4) if margin > 0 else 0.0
        except (TypeError, ValueError):
            pass

    print(f"\n===== {a.bot} · 최근 {a.days:.0f}일 =====")
    print(f"  교정 대상 {fixed}건 · 매칭 실패 {unmatched}건")
    if samples:
        print(f"  {'시각':12} {'종목':10} {'기존':>10} {'원장':>10}")
        for t, s, c, rl in samples:
            print(f"  {t:12} {s:10} {c:+10.4f} {rl:+10.4f}")
        if fixed > len(samples):
            print(f"  ... 외 {fixed-len(samples)}건")
    print(f"  손익 총변화 {delta:+.4f}  (CSV가 그만큼 부풀려져 있었다)")

    if fixed == 0:
        print("  ✅ 교정 불필요")
        return
    if not a.apply:
        print("  (점검만 수행 — 반영하려면 --apply)")
        return

    bak = path + ".bak_fixval_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, bak)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)
    print(f"  ✅ {fixed}건 교정  (백업: {os.path.basename(bak)})")


asyncio.run(main())
