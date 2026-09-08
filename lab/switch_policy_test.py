#!/usr/bin/env python3
"""switch_policy_test.py — '5전 3패 방향반전' vs '쿨다운 후 같은 방향' 비교 검증.

질문
  수익률이 떨어질 때 방향을 뒤집는 게(현행) 나은가, 아니면 일정 시간 쉬었다가
  같은 방향으로 계속하는 게 나은가?

왜 검증이 가능한가
  8407·8409는 청개구리(Bluefrog) 모드가 **신호 방향을 그대로 뒤집는** 구조다.
  따라서 실제 체결된 각 거래에 대해 "반대 방향이었다면" 어떻게 됐을지를
  실제 1분봉으로 되짚을 수 있다. 신호를 재현할 필요가 없다.

방법
  ① 거래소 원장에서 실제 거래를 복원한다 (진입 시각·종목·방향·실현손익).
  ② 각 거래의 진입 시각부터 1분봉을 훑어, **같은 손절·익절 폭**을 반대 방향에
     적용했을 때 어느 쪽에 먼저 닿았는지 판정한다 → 반대방향 손익(반사실).
  ③ 세 정책의 누적 손익을 비교한다.
       P0 현행    실제 방향 그대로 (5전3패 시 반전)
       P1 고정    스위칭 없이 '순방향' 신호만 따랐을 때
       P2 쿨다운  5전3패 감지 시 N시간 진입 중단, 방향은 유지

손절·익절 폭은 실측 중앙값을 쓴다(8407: 익절 +1.03% / 손절 −0.65% 가격 기준).
설정값(ATR 배수)은 종목·시점마다 달라 재현이 어렵고, 실측 중앙값이 실제 체결
분포를 더 잘 대표한다.

한계 — 반드시 함께 보고할 것
  전환 이벤트가 14회뿐이라 **통계적 확정은 불가능**하다. 부호와 크기의 방향만 본다.
"""
import asyncio
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd

BASE = "/Users/l/project"


async def load_trades(ex, symbols, since):
    """체결을 포지션 단위로 묶어 (진입시각, 종목, 방향, 실현손익)을 복원."""
    out = []
    for sym in symbols:
        try:
            fills = await ex.fetch_my_trades(sym, since=since, limit=1000)
        except Exception:
            continue
        pos, ets, eside, pnl, epx = 0.0, None, None, 0.0, 0.0
        for f in sorted(fills, key=lambda x: x["timestamp"]):
            amt = float(f.get("amount") or 0)
            signed = amt if f.get("side") == "buy" else -amt
            rp = float((f.get("info") or {}).get("realizedPnl") or 0)
            if pos == 0 and abs(signed) > 0:
                ets, eside, pnl = f["timestamp"], ("long" if signed > 0 else "short"), 0.0
                epx = float(f.get("price") or 0)
            pos += signed
            pnl += rp
            if abs(pos) < 1e-12 and ets:
                out.append(dict(sym=sym, ts=ets, side=eside, px=epx, pnl=pnl))
                ets, pos, pnl = None, 0.0, 0.0
    return sorted(out, key=lambda x: x["ts"])


async def counterfactual(ex, tr, tp_pct, sl_pct, max_hours):
    """같은 진입 시각·반대 방향에서 손절/익절 중 어디에 먼저 닿았는지 1분봉으로 판정."""
    since = tr["ts"] - 60_000
    try:
        o = await ex.fetch_ohlcv(tr["sym"], "1m", since=since, limit=int(max_hours * 60) + 10)
    except Exception:
        return None
    if not o:
        return None
    px = tr["px"]
    if px <= 0:
        return None
    opp = "short" if tr["side"] == "long" else "long"
    if opp == "long":
        tp, sl = px * (1 + tp_pct), px * (1 - sl_pct)
    else:
        tp, sl = px * (1 - tp_pct), px * (1 + sl_pct)
    for _, _, hi, lo, _, _ in [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in o if r[0] >= tr["ts"]]:
        if opp == "long":
            if lo <= sl:
                return -sl_pct
            if hi >= tp:
                return tp_pct
        else:
            if hi >= sl:
                return -sl_pct
            if lo <= tp:
                return tp_pct
    last = o[-1][4]
    r = (last / px - 1) * (1 if opp == "long" else -1)
    return float(np.clip(r, -sl_pct, tp_pct))


def simulate(trades, cf, cool_hours, SL_PCT=0.0065):
    """P0 실제 / P1 고정(스위칭 없음) / P2 쿨다운 후 방향 유지."""
    # [단위 환산] 반사실 c는 **가격 수익률**이고 실제 pnl은 **USDT**다.
    # c × 명목가 = USDT가 되도록 명목가를 실측에서 역산한다.
    # 손절로 끝난 거래는 |pnl| ≈ sl_pct × 명목가 이므로 그 관계로 추정한다.
    real = [t["pnl"] for t in trades]
    losses = [abs(x) for x in real if x < 0]
    notional = (np.median(losses) / SL_PCT) if losses else 1.0

    p0 = sum(real)

    # P1: 스위칭이 없었다면 — 방향이 뒤집힌 구간의 거래는 반대 손익이 된다.
    # 첫 거래의 방향을 '기준 방향'으로 두고, 이후 방향이 바뀐 거래는 반사실로 대체.
    p1 = 0.0
    base_side = trades[0]["side"] if trades else None
    for t, c in zip(trades, cf):
        if c is None:
            p1 += t["pnl"]; continue
        p1 += t["pnl"] if t["side"] == base_side else c * notional

    # P2: 3연패 감지 시 cool_hours 동안 진입 중단(그 사이 거래는 없던 것으로),
    #     방향은 그대로 유지 → P1 기반에서 쿨다운 구간을 제외
    p2, streak, block_until = 0.0, 0, 0
    for t, c in zip(trades, cf):
        if t["ts"] < block_until:
            continue                      # 쿨다운 중 — 진입하지 않았다고 본다
        v = t["pnl"] if (base_side is None or t["side"] == base_side or c is None) else c * notional
        p2 += v
        streak = streak + 1 if v < 0 else 0
        if streak >= 3:
            block_until = t["ts"] + int(cool_hours * 3600 * 1000)
            streak = 0
    return p0, p1, p2


async def main():
    bot = sys.argv[1] if len(sys.argv) > 1 else "8407"
    days = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
    tp_pct = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0103
    sl_pct = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0065

    d = os.path.join(BASE, bot)
    sys.path.insert(0, d); os.chdir(d)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(d, ".env"), override=False)
    from core.api_keys import load_api_keys
    load_api_keys(override=True)
    from core.config import CFG
    from core.exchange import BinanceClient

    cl = BinanceClient(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", ""))
    await cl.load_markets()
    ex = cl.exchange
    since = int((dt.datetime.now() - dt.timedelta(days=days)).timestamp() * 1000)
    trades = await load_trades(ex, CFG.SYMBOL_WHITELIST or [], since)
    if len(trades) < 10:
        print("  거래 %d건 — 표본 부족" % len(trades)); await ex.close(); return

    cf = []
    for t in trades:
        cf.append(await counterfactual(ex, t, tp_pct, sl_pct, 12))

    n_cf = sum(1 for c in cf if c is not None)
    print("%s · 최근 %.0f일 · 거래 %d건 (반사실 산출 %d건)" % (bot, days, len(trades), n_cf))
    print("  가정 익절 +%.2f%% / 손절 −%.2f%% (실측 중앙값)\n" % (tp_pct * 100, sl_pct * 100))

    sides = [t["side"] for t in trades]
    sw = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
    print("  실제 방향 전환 %d회 (거래 %d건당)\n" % (sw, len(trades)))

    _L=[abs(t["pnl"]) for t in trades if t["pnl"]<0]
    print("  추정 명목가 $%.2f (손절 중앙값 %.4f ÷ %.4f)\n" % (np.median(_L)/sl_pct if _L else 0, np.median(_L) if _L else 0, sl_pct))
    print("  %-28s %12s" % ("정책", "누적손익"))
    p0, p1, _ = simulate(trades, cf, 0, sl_pct)
    print("  %-28s %+12.4f" % ("P0 현행 (5전3패 반전)", p0))
    print("  %-28s %+12.4f" % ("P1 고정 (스위칭 없음)", p1))
    for ch in (2, 4, 6, 12):
        _, _, p2 = simulate(trades, cf, ch, sl_pct)
        print("  %-28s %+12.4f" % ("P2 쿨다운 %d시간 + 방향유지" % ch, p2))
    await ex.close()


asyncio.run(main())
