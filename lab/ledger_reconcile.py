#!/usr/bin/env python3
"""ledger_reconcile.py — 거래소 원장을 기준으로 봇 CSV의 누락 청산을 찾아 채운다.

왜 필요한가
  봇은 `_prev_position_symbols - current`로 청산을 감지한다. 이 스냅샷 방식은
  봇이 그 포지션을 추적하고 있었어야만 동작한다. 재기동·동시 다중 청산·
  추적 유실이 겹치면 청산이 CSV에 **영영 남지 않는다**.

  실측(8409, 09-07~09-10): 원장 31건 중 **13건 누락**.
  누락분이 대부분 손실이라 CSV는 항상 실제보다 좋아 보인다.
      CSV +0.2831  vs  원장 -0.0674
  이 상태로는 성과 판정도, 5전3패 스위칭 판정도 전부 틀어진다.

방침
  ① 진실은 거래소 원장이다. CSV를 원장에 맞춘다(반대가 아니다).
  ② **추정값을 만들지 않는다.** 청산시각·수량·가격·손익은 원장 실측만 쓴다.
     진입 정보가 없으면 비워 두고 '원장복원'으로 표기한다.
  ③ 기존 행은 건드리지 않는다. 누락분만 덧붙인다.
  ④ 기본은 dry-run이다. `--apply`를 줘야 파일을 쓴다.

사용
    python3 ledger_reconcile.py 8409            # 점검만
    python3 ledger_reconcile.py 8409 --apply    # 누락분 반영
    python3 ledger_reconcile.py all --days 14
"""
import argparse
import asyncio
import csv
import datetime as dt
import os
import shutil
import sys

BASE = "/Users/l/project"
BNC = ("8407", "8409", "8410")
OKX = ("8401", "8402")

# CSV 헤더 (봇이 쓰는 순서 그대로)
COLS = ["시간", "심볼", "유형", "방향", "가격", "수량", "수익(USDT)", "수익률(%)",
        "청산유형", "레버리지", "주문ID", "체결ID", "수수료(USDT)", "매매모드"]


def _load_client(bot):
    d = os.path.join(BASE, bot)
    sys.path.insert(0, d)
    os.chdir(d)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(d, ".env"), override=False)
    from core.api_keys import load_api_keys
    load_api_keys(override=True)
    return d


def _unload(d):
    for k in list(sys.modules):
        if k.startswith("core"):
            del sys.modules[k]
    if d in sys.path:
        sys.path.remove(d)


async def ledger_cycles(bot, since_ms):
    """원장에서 포지션 사이클(진입→전량청산)을 복원한다. 손익은 실측만 쓴다."""
    d = _load_client(bot)
    out = []
    if bot in BNC:
        from core.exchange import BinanceClient
        cl = BinanceClient(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", ""))
        await cl.load_markets()
        ex = cl.exchange
        # 원장에서 거래가 있었던 심볼만 추린다 (전 종목 순회는 낭비)
        syms, s = set(), since_ms
        while True:
            rows = await ex.fapiPrivateGetIncome({"startTime": s, "limit": 1000})
            if not rows:
                break
            for r in rows:
                if r["incomeType"] == "REALIZED_PNL" and float(r["income"] or 0) != 0:
                    syms.add(r["symbol"])
            if len(rows) < 1000:
                break
            s = int(rows[-1]["time"]) + 1
        for sym in sorted(syms):
            try:
                tr = await ex.fapiPrivateGetUserTrades(
                    {"symbol": sym, "startTime": since_ms, "limit": 500})
            except Exception:
                continue
            pos = 0.0
            ets = None
            pnl = fee = 0.0
            lev = 3
            for t in sorted(tr, key=lambda x: int(x["time"])):
                q = float(t["qty"]) * (1 if t["side"] == "BUY" else -1)
                if abs(pos) < 1e-12 and q != 0:
                    ets, pnl, fee = int(t["time"]), 0.0, 0.0
                pos += q
                pnl += float(t.get("realizedPnl") or 0)
                fee += float(t.get("commission") or 0)
                if abs(pos) < 1e-12 and ets is not None:
                    out.append(dict(
                        ts=int(t["time"]), sym=sym, price=float(t["price"]),
                        qty=abs(float(t["qty"])), pnl=round(pnl, 6),
                        fee=round(fee, 6), side=t["side"].lower(),
                        order_id=str(t.get("orderId") or ""),
                        trade_id=str(t.get("id") or ""), lev=lev))
                    ets = None
        await ex.close()
    _unload(d)
    return sorted(out, key=lambda x: x["ts"])


def csv_logged(path, since_ms):
    """CSV에 이미 있는 청산 키 집합. 체결ID 우선, 없으면 (종목, 분) 조합."""
    ids, keys = set(), set()
    if not os.path.exists(path):
        return ids, keys
    since_s = dt.datetime.fromtimestamp(since_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("유형") != "청산" or r.get("시간", "") < since_s:
                continue
            tid = (r.get("체결ID") or "").strip()
            if tid:
                ids.add(tid)
            keys.add((r["심볼"].split("/")[0], r["시간"][:16]))
    return ids, keys


def to_row(c, mode):
    ts = dt.datetime.fromtimestamp(c["ts"] / 1000).strftime("%Y-%m-%d %H:%M:%S")
    sym = c["sym"].replace("USDT", "") + "/USDT:USDT"
    # 수익률은 명목가 대비로만 낸다. 진입가를 모르면 추정하지 않는다.
    notional = c["price"] * c["qty"]
    pct = (c["pnl"] / (notional / c["lev"]) * 100) if notional > 0 else 0.0
    return {
        "시간": ts, "심볼": sym, "유형": "청산", "방향": c["side"],
        "가격": c["price"], "수량": c["qty"], "수익(USDT)": c["pnl"],
        "수익률(%)": round(pct, 4), "청산유형": "원장복원", "레버리지": c["lev"],
        "주문ID": c["order_id"], "체결ID": c["trade_id"],
        "수수료(USDT)": abs(c["fee"]), "매매모드": mode,
    }


async def run(bot, days, apply):
    since = int((dt.datetime.now() - dt.timedelta(days=days)).timestamp() * 1000)
    path = os.path.join(BASE, bot, "data", "trade_history.csv")
    cycles = await ledger_cycles(bot, since)
    ids, keys = csv_logged(path, since)

    missing = []
    for c in cycles:
        tid = c["trade_id"]
        k = (c["sym"].replace("USDT", ""),
             dt.datetime.fromtimestamp(c["ts"] / 1000).strftime("%Y-%m-%d %H:%M"))
        if tid and tid in ids:
            continue
        if k in keys:
            continue
        missing.append(c)

    tot_led = sum(c["pnl"] for c in cycles)
    tot_mis = sum(c["pnl"] for c in missing)
    print(f"\n===== {bot} · 최근 {days}일 =====")
    print(f"  원장 청산 {len(cycles)}건 (손익 {tot_led:+.4f})")
    print(f"  CSV 누락  {len(missing)}건 (손익 {tot_mis:+.4f})")
    if missing:
        loss = sum(1 for c in missing if c["pnl"] < 0)
        print(f"    └ 손실 {loss}건 / 이익 {len(missing)-loss}건"
              f"  → CSV가 실제보다 {-tot_mis:+.4f} 좋아 보임")
        for c in missing[:12]:
            t = dt.datetime.fromtimestamp(c["ts"] / 1000).strftime("%m-%d %H:%M:%S")
            print(f"      {t}  {c['sym'].replace('USDT',''):10} {c['pnl']:+8.4f}")
        if len(missing) > 12:
            print(f"      ... 외 {len(missing)-12}건")

    if not missing:
        print("  ✅ 누락 없음")
        return 0
    if not apply:
        print("  (점검만 수행 — 반영하려면 --apply)")
        return len(missing)

    # 매매모드는 기존 CSV의 마지막 값을 따른다(역방향/순방향 표기 유지)
    mode = "순방향"
    try:
        with open(path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        if rows:
            mode = rows[-1].get("매매모드") or mode
    except Exception:
        pass

    bak = path + ".bak_reconcile_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(path, bak)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        for c in missing:
            w.writerow(to_row(c, mode))
    print(f"  ✅ {len(missing)}건 반영  (백업: {os.path.basename(bak)})")
    return len(missing)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot")
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    bots = BNC if a.bot == "all" else (a.bot,)
    total = 0
    for b in bots:
        try:
            total += await run(b, a.days, a.apply)
        except Exception as e:
            print(f"\n===== {b} =====\n  오류: {str(e)[:140]}")
    print(f"\n총 누락 {total}건")


asyncio.run(main())
