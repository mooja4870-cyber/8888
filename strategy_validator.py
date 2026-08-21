#!/usr/bin/env python3
"""
strategy_validator.py — 전략 배포 전 합격 기준 검증

배경
────
이번 주 실측에서, 백테스트 한 번 돌려 플러스면 배포하는 방식이 반복해서 실패했다.
같은 전략이 구간에 따라 부호가 뒤집혔다(패트릭닐 +144%/−29%/−14%,
이중볼린저 −101%/+30%/+235%, MFI 다이버전스 +25.6%/−23.4%/+10.6%).
"최근 구간에 잘 맞는 것"을 찾아냈을 뿐 지속적 엣지가 아니었다는 뜻이다.

그래서 배포 전 통과해야 할 기준을 명시한다. **넷 다 통과해야 합격**이다.
  1. 표본     — 최소 100건, 30일 이상
  2. 구간 안정 — 3분할했을 때 전 구간 플러스 (하나라도 마이너스면 탈락)
  3. 강건성   — 손익비를 ±30% 흔들어도 플러스 유지 (정점에서만 좋으면 과최적화)
  4. 수수료 내성 — 수수료를 2배로 잡아도 플러스

설계
────
* 신호 생성은 심볼당 1회만 수행하고(비용이 큼), 청산 시뮬레이션은 그 결과를 재사용해
  손익비·수수료를 바꿔가며 값싸게 반복한다.
* 진입가·손절가는 전략이 준 값을 그대로 쓰고, 익절가만 손익비로 재계산한다.
* 미래참조가 없도록 신호 시점 i까지의 데이터만 전략에 넘긴다.

사용
────
    python3 strategy_validator.py <봇번호> [타임프레임] [봉수] [심볼수]
    예) python3 strategy_validator.py 8408 15m 3000 15
"""
import asyncio
import os
import statistics
import sys
import time

BARS_PER_TF = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}

# ── 합격 기준 ────────────────────────────────────────────────
MIN_TRADES   = 100     # 표본 하한
MIN_DAYS     = 30      # 기간 하한(일)
RR_SHIFT     = 0.30    # 강건성 검사 시 손익비 흔드는 폭(±30%)
FEE_BASE     = 0.001   # 왕복 수수료·슬리피지 기본 가정(0.1%/건)
FEE_STRESS   = 2.0     # 수수료 내성 검사 배수


async def fetch(client, sym, tf, want):
    """페이지네이션으로 원하는 봉수를 채운다.

    페이지 크기는 거래소마다 다르다(바이낸스 1000, OKX 300). 종전에는
    `len(b) < 1000`이면 끝으로 간주해 OKX에서 첫 300봉만 받고 중단됐고,
    그 결과 모든 심볼이 최소 봉수 미달로 통째 제외돼 '거래 0건'이 나왔다.
    페이지 크기를 가정하지 말고 **진행이 멈췄을 때**만 종료한다.
    """
    ex = client.exchange
    ms = BARS_PER_TF[tf] * 60 * 1000
    since = int(time.time() * 1000) - want * ms
    out = []
    guard = 0
    while len(out) < want and guard < 40:
        guard += 1
        try:
            b = await ex.fetch_ohlcv(sym, tf, since=since, limit=1000)
        except Exception:
            break
        if not b:
            break
        nxt = b[-1][0] + 1
        if nxt <= since:            # 더 이상 앞으로 나아가지 못하면 종료
            break
        out += b
        since = nxt
    return out


def collect_signals(strategy, df, sym, min_bars):
    """심볼당 1회 주사. (진입idx, 방향, 진입가, 손절가, 원손익비)를 모은다.

    같은 신호로 연속 진입하지 않도록, 한 번 잡으면 청산될 때까지 건너뛴다.
    """
    import pandas as pd
    n = len(df)
    sigs = []
    i = min_bars
    while i < n - 1:
        s = strategy.generate_signal(df.iloc[:i], sym)
        if s.direction == "none":
            i += 1
            continue
        e, sl, tp = s.close, s.swing_sl_price, s.tp1_price
        if not (e > 0 and sl > 0 and tp > 0):
            i += 1
            continue
        risk = abs(e - sl) / e
        if risk <= 0:
            i += 1
            continue
        sigs.append({"i": i, "dir": s.direction, "e": e, "risk": risk,
                     "rr": abs(tp - e) / e / risk})
        i += 1
    return sigs


def simulate(sigs, df, rr_override=None, fee=FEE_BASE, hold_bars=None):
    """신호 목록을 청산까지 시뮬레이션. 중복 보유를 막아 현실성을 맞춘다."""
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    n = len(df)
    out = []
    busy_until = -1
    for s in sigs:
        i = s["i"]
        if i <= busy_until:          # 이미 보유 중이면 신규 진입하지 않음
            continue
        e, risk = s["e"], s["risk"]
        rr = rr_override if rr_override is not None else s["rr"]
        if s["dir"] == "long":
            sl, tp = e * (1 - risk), e * (1 + risk * rr)
        else:
            sl, tp = e * (1 + risk), e * (1 - risk * rr)
        end = n - 1 if hold_bars is None else min(n - 1, i + hold_bars)
        res = None
        j = i
        while j <= end:
            if s["dir"] == "long":
                if l[j] <= sl:
                    res = -risk; break
                if h[j] >= tp:
                    res = risk * rr; break
            else:
                if h[j] >= sl:
                    res = -risk; break
                if l[j] <= tp:
                    res = risk * rr; break
            j += 1
        if res is None:
            res = (c[end] - e) / e if s["dir"] == "long" else (e - c[end]) / e
        out.append(res)
        busy_until = j
    net = sum(out) - fee * len(out)
    wins = sum(1 for x in out if x > 0)
    return {"n": len(out), "win": wins, "net": net,
            "wr": (100.0 * wins / len(out)) if out else 0.0}


def simulate_real(sigs, df, cfg, rr_override=None, fee=FEE_BASE):
    """실제 봇의 청산 경로를 재현한 시뮬레이션.

    단순 SL/TP만 보면 실거래와 크게 어긋난다. 실측(8408)에서 수익의 거의 전부가
    ATR 트레일링 청산(+4.35)에서 나오고 고정 SL/TP는 오히려 마이너스(−0.35)였다.
    아래 순서로 실제 트레이더와 같은 단계를 태운다.

      ① 본전보호  : +BE_GUARD_TRIGGER 도달 시 손절선을 본전(+PROTECT)으로 상향
      ② 분할익절  : +PARTIAL_TP_TRIGGER 도달 시 PARTIAL_FRACTION 만큼 확정,
                    잔량은 샹들리에 트레일링으로 전환
      ③ 트레일링  : 고점 − CHANDELIER_K × ATR (숏은 대칭)
      ④ 시간청산  : MAX_HOLDING_HOURS 초과 시 종가 청산
    한 봉 안에서는 보수적으로 **손절을 익절보다 먼저** 확인한다.
    """
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = df["_atr"].values
    n = len(df)
    g = lambda k, d: float(cfg.get(k, d) if cfg.get(k) is not None else d)
    be_on   = bool(cfg.get("USE_BE_GUARD", True))
    be_trig = g("BE_GUARD_TRIGGER_PCT", 0.012)
    be_prot = g("BE_GUARD_PROTECT_PCT", 0.001)
    pt_on   = bool(cfg.get("USE_PARTIAL_TP", True))
    pt_trig = g("PARTIAL_TP_TRIGGER_PCT", 0.015)
    pt_frac = g("PARTIAL_TP_FRACTION", 0.5)
    k_ch    = g("CHANDELIER_K", 3.0)
    hold    = int(g("MAX_HOLDING_HOURS", 6.0) * 60 / BARS_PER_TF[TF_NOW]) if g("MAX_HOLDING_HOURS", 6.0) > 0 else 10**9

    out, busy_until = [], -1
    for s in sigs:
        i = s["i"]
        if i <= busy_until:
            continue
        e, risk = s["e"], s["risk"]
        rr = rr_override if rr_override is not None else s["rr"]
        long = s["dir"] == "long"
        sl = e * (1 - risk) if long else e * (1 + risk)
        tp = e * (1 + risk * rr) if long else e * (1 - risk * rr)
        realized, remain = 0.0, 1.0
        partial_done, trailing = False, False
        peak = e
        end = min(n - 1, i + hold)
        j, done = i, False
        while j <= end:
            hi, lo = h[j], l[j]
            gain = (hi - e) / e if long else (e - lo) / e      # 봉 내 최대 유리 폭
            # ① 본전보호
            if be_on and gain >= be_trig:
                sl = max(sl, e * (1 + be_prot)) if long else min(sl, e * (1 - be_prot))
            # ② 분할익절 → 트레일링 전환
            if pt_on and not partial_done and gain >= pt_trig:
                realized += pt_frac * pt_trig
                remain -= pt_frac
                partial_done, trailing = True, True
                peak = hi if long else lo
            # ③ 트레일링 스탑 갱신
            if trailing:
                peak = max(peak, hi) if long else min(peak, lo)
                a = atr[j] if atr[j] == atr[j] else 0.0
                ch = (peak - k_ch * a) if long else (peak + k_ch * a)
                sl = max(sl, ch) if long else min(sl, ch)
            # 손절 우선 확인 (보수적)
            if (long and lo <= sl) or (not long and hi >= sl):
                r = (sl - e) / e if long else (e - sl) / e
                realized += remain * r
                done = True
                break
            if not partial_done and ((long and hi >= tp) or (not long and lo <= tp)):
                realized += remain * (risk * rr)
                done = True
                break
            j += 1
        if not done:
            last = c[min(j, end)]
            r = (last - e) / e if long else (e - last) / e
            realized += remain * r
        out.append(realized)
        busy_until = min(j, end)
    net = sum(out) - fee * len(out)
    wins = sum(1 for x in out if x > 0)
    return {"n": len(out), "win": wins, "net": net,
            "wr": (100.0 * wins / len(out)) if out else 0.0}


TF_NOW = "15m"


def slice_by_index(sigs, df, lo, hi):
    return [s for s in sigs if lo <= s["i"] < hi]


async def main():
    bot = sys.argv[1] if len(sys.argv) > 1 else "8408"
    tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    globals()["TF_NOW"] = tf
    want = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
    nsym = int(sys.argv[4]) if len(sys.argv) > 4 else 15

    base = f"/Users/l/project/{bot}"
    os.chdir(base)
    sys.path.insert(0, base)
    from dotenv import load_dotenv
    load_dotenv(override=True)
    try:
        from core.api_keys import load_api_keys
        load_api_keys(override=True)
    except Exception:
        pass
    import pandas as pd
    from core.config import CFG
    from core.exchange import OKXClient
    from core.strategy import StrategyEngine

    ex_id = str(getattr(CFG, "EXCHANGE_ID", "okx")).lower()
    if ex_id == "binance":
        key, sec, pw = os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", ""), ""
    else:
        key, sec, pw = os.getenv("OKX_API_KEY", ""), os.getenv("OKX_SECRET_KEY", ""), os.getenv("OKX_PASSPHRASE", "")

    client = OKXClient(key, sec, pw)
    await client.load_markets()
    tickers = await client.get_tickers()
    bl = set(getattr(CFG, "SYMBOL_BLACKLIST", []) or [])
    # 실거래에서 주문이 거부되는 종목은 검증에서도 제외해야 공정하다.
    # 바이낸스 토큰화 주식·ETF(TradFi Perps)는 약관 미동의 계정에서 -4411로 전량 거부되는데,
    # 상위 30종목의 절반 이상을 차지해 그대로 두면 매매할 수 없는 종목으로 성적을 매기게 된다.
    mk = client.exchange.markets

    def tradable(s):
        info = (mk.get(s) or {}).get("info") or {}
        return not (info.get("contractType") == "TRADIFI_PERPETUAL"
                    or info.get("underlyingType") == "EQUITY")

    syms = [s for s in tickers if s.endswith("/USDT:USDT") and s not in bl and tradable(s)]
    syms = sorted(syms, key=lambda s: tickers[s].get("volume", 0) or 0, reverse=True)[:nsym]

    days = want * BARS_PER_TF[tf] / 60 / 24
    strat = StrategyEngine()
    head = open(f"{base}/core/strategy.py", encoding="utf-8").read().splitlines()[1][:50]
    print(f"  전략: {head}")
    print(f"  봇 {bot} · {ex_id.upper()} · {tf} · {want}봉({days:.1f}일) · {len(syms)}종목")
    print("  " + "─" * 66, flush=True)

    all_sigs, frames = {}, {}
    min_bars = 260
    for s in syms:
        raw = await fetch(client, s, tf, want)
        if len(raw) < min_bars + 100:
            continue
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        # 샹들리에 트레일링용 ATR (실제 트레이더와 동일 기간)
        _pc = df["close"].shift(1)
        _tr = pd.concat([df["high"] - df["low"], (df["high"] - _pc).abs(), (df["low"] - _pc).abs()], axis=1).max(axis=1)
        df["_atr"] = _tr.ewm(span=int(getattr(CFG, "ATR_PERIOD", 14)), adjust=False).mean()
        frames[s] = df
        all_sigs[s] = collect_signals(strat, df, s, min_bars)
        print(f"    {s.split('/')[0]:<12} {len(df):>4}봉 · 신호 {len(all_sigs[s]):>3}건", flush=True)
    await client.exchange.close()

    cfgd = {k: getattr(CFG, k, None) for k in
            ("USE_BE_GUARD","BE_GUARD_TRIGGER_PCT","BE_GUARD_PROTECT_PCT","USE_PARTIAL_TP",
             "PARTIAL_TP_TRIGGER_PCT","PARTIAL_TP_FRACTION","CHANDELIER_K","MAX_HOLDING_HOURS")}

    def run(rr=None, fee=FEE_BASE, lo=0, hi=10**9, real=True):
        tot = {"n": 0, "win": 0, "net": 0.0}
        for s, df in frames.items():
            sub = slice_by_index(all_sigs[s], df, lo, hi)
            if not sub:
                continue
            r = (simulate_real(sub, df, cfgd, rr_override=rr, fee=fee) if real
                 else simulate(sub, df, rr_override=rr, fee=fee))
            tot["n"] += r["n"]; tot["win"] += r["win"]; tot["net"] += r["net"]
        tot["wr"] = 100.0 * tot["win"] / tot["n"] if tot["n"] else 0.0
        return tot

    print("\n  ══ 기준 1: 표본 ══", flush=True)
    base_r = run()
    ok1 = base_r["n"] >= MIN_TRADES and days >= MIN_DAYS
    print(f"    거래 {base_r['n']}건 (기준 {MIN_TRADES}) · 기간 {days:.1f}일 (기준 {MIN_DAYS}) → {'통과' if ok1 else '탈락'}")
    print(f"    전체: 승률 {base_r['wr']:.0f}% · 순손익 {base_r['net']*100:+.2f}% · 월환산 {base_r['net']*100*30/days:+.1f}%")

    print("\n  ══ 기준 2: 구간 안정성 (3분할, 전 구간 플러스여야 함) ══", flush=True)
    third = want // 3
    segs, ok2 = [], True
    for k, (lo, hi) in enumerate([(0, third), (third, 2*third), (2*third, want)], 1):
        r = run(lo=lo, hi=hi)
        segs.append(r)
        good = r["net"] > 0
        ok2 = ok2 and good
        print(f"    {k}구간 {r['n']:>3}건 승률{r['wr']:>3.0f}% 순{r['net']*100:>+7.2f}% {'✅' if good else '❌'}")
    print(f"    → {'통과' if ok2 else '탈락'}")

    print(f"\n  ══ 기준 3: 강건성 (손익비 ±{int(RR_SHIFT*100)}% 흔들기) ══", flush=True)
    rrs = [s["rr"] for x in all_sigs.values() for s in x]
    med = statistics.median(rrs) if rrs else 2.0
    ok3 = True
    for label, mult in (("-30%", 1 - RR_SHIFT), ("기준", 1.0), ("+30%", 1 + RR_SHIFT)):
        r = run(rr=med * mult)
        good = r["net"] > 0
        ok3 = ok3 and good
        print(f"    손익비 {med*mult:.2f} ({label:>4}) {r['n']:>3}건 승률{r['wr']:>3.0f}% 순{r['net']*100:>+7.2f}% {'✅' if good else '❌'}")
    print(f"    → {'통과' if ok3 else '탈락'}")

    print(f"\n  ══ 기준 4: 수수료 내성 ({FEE_STRESS:.0f}배) ══", flush=True)
    r = run(fee=FEE_BASE * FEE_STRESS)
    ok4 = r["net"] > 0
    print(f"    수수료 {FEE_BASE*FEE_STRESS*100:.1f}%/건 → 순 {r['net']*100:+.2f}% {'✅' if ok4 else '❌'}")
    print(f"    → {'통과' if ok4 else '탈락'}")

    print("\n  " + "═" * 66)
    passed = sum([ok1, ok2, ok3, ok4])
    print(f"  최종: {passed}/4 통과 → {'🟢 배포 적격' if passed == 4 else '🔴 배포 부적격'}")


if __name__ == "__main__":
    asyncio.run(main())
