#!/usr/bin/env python3
"""verify_xfunding.py — 거래소간 펀딩비 차이의 지속성 검증

배경
────
현 시점 스냅샷(2026-08-14)에서 바이낸스-OKX 펀딩비 차이가 유동성 확보 종목
기준 상위 5개 평균 연 73.5%로 나왔다. 그러나 그건 한 순간의 값이다.
차이가 하루도 못 가면 수수료(왕복 0.08%)조차 못 건진다.

검증 질문
────────
① 차이가 며칠 지속되는가 — 한 번 잡으면 얼마나 들고 갈 수 있나
② 지금 상위인 종목이 내일도 상위인가 — 종목 선정이 의미가 있나
③ 실제로 손에 쥐는 수익은 얼마인가 — 수수료 차감 후

방법
────
양 거래소의 과거 펀딩비 이력(8시간 주기)을 받아 시점별 차이를 계산한다.
'현 시점 차이 상위 N개'를 골라 이후 며칠간 그 차이가 유지되는지 추적한다.
백테스트가 아니라 **관측**이다 — 실제 체결·슬리피지는 반영하지 않으므로
여기서 나온 값은 **상한**으로 봐야 한다.
"""
import asyncio, statistics, sys, time
import ccxt.async_support as ccxt_async

DAYS = 45      # 호라이즌 15일을 여유 있게 담으려면 이력이 더 필요하다
TOPN = 5
FEE_ROUNDTRIP = 0.0008      # 양쪽 선물 메이커 왕복 0.02%×4


async def fetch_hist(ex, sym, since, label):
    out = {}
    try:
        h = await ex.fetch_funding_rate_history(sym, since=since, limit=1000)
    except Exception:
        return out
    for x in h:
        # 8시간 슬롯으로 정규화
        slot = int(x["timestamp"] // (8 * 3600 * 1000))
        try:
            out[slot] = float(x["fundingRate"])
        except (TypeError, ValueError):
            pass
    return out


async def main():
    bn = ccxt_async.binance({"options": {"defaultType": "future"}, "enableRateLimit": True})
    ok = ccxt_async.okx({"enableRateLimit": True})
    await bn.load_markets(); await ok.load_markets()
    bt = await bn.fetch_tickers()
    since = int((time.time() - DAYS * 86400) * 1000)

    # 유동성 있고 양 거래소에 다 있는 종목
    cands = []
    for s, mk in bn.markets.items():
        if not (s.endswith("/USDT:USDT") and mk.get("swap")):
            continue
        info = mk.get("info") or {}
        if info.get("contractType") == "TRADIFI_PERPETUAL" or info.get("underlyingType") == "EQUITY":
            continue
        if s not in ok.markets:
            continue
        vol = (bt.get(s) or {}).get("quoteVolume") or 0
        if vol >= 5_000_000:
            cands.append((vol, s))
    cands.sort(reverse=True)
    syms = [s for _, s in cands[:40]]
    print(f"  후보 {len(syms)}종목 (거래대금 $5M↑ · TradFi 제외) · 최근 {DAYS}일 펀딩 이력 수집", flush=True)

    hist = {}
    for s in syms:
        b = await fetch_hist(bn, s, since, "bn")
        o = await fetch_hist(ok, s, since, "ok")
        common = sorted(set(b) & set(o))
        if len(common) < DAYS * 3 * 0.5:      # 절반 이상 있어야 채택
            continue
        hist[s] = {t: b[t] - o[t] for t in common}
    print(f"  이력 확보 {len(hist)}종목", flush=True)
    if not hist:
        await bn.close(); await ok.close(); return

    slots = sorted({t for d in hist.values() for t in d})
    ann = lambda f: f * 3 * 365 * 100

    # ① 지속성: 어느 시점의 상위 N개를 잡으면 이후 며칠간 차이가 유지되나
    print("\n  ══ ① 상위 종목을 잡은 뒤 경과별 평균 차이 (연%) ══")
    print(f"  {'경과':<10}{'평균 차이':>12}{'0 이상 비율':>14}")
    horizons = [0, 3, 9, 21, 45]             # 8시간 슬롯 → 0일/1일/3일/7일/15일
    # 최대 호라이즌이 이력 길이와 같으면 시작점이 하나도 안 남는다(첫 실행에서 실측).
    acc = {h: [] for h in horizons}
    starts = slots[:-max(horizons)] if len(slots) > max(horizons) else []
    for t0 in starts[::3]:
        cur = sorted(((abs(hist[s].get(t0, 0)), s) for s in hist if t0 in hist[s]), reverse=True)[:TOPN]
        if not cur:
            continue
        for h in horizons:
            vals = []
            for _, s in cur:
                d0 = hist[s].get(t0)
                d1 = hist[s].get(t0 + h)
                if d0 is None or d1 is None:
                    continue
                # 진입 방향 기준(부호 고정)으로 이후 차이를 평가
                vals.append(d1 if d0 > 0 else -d1)
            if vals:
                acc[h].append(statistics.mean(vals))
    for h in horizons:
        v = acc[h]
        if not v:
            continue
        days = h * 8 / 24
        pos = 100 * sum(1 for x in v if x > 0) / len(v)
        print(f"  {days:>5.0f}일 뒤{ann(statistics.mean(v)):>12.1f}%{pos:>13.0f}%")

    # ③ 실현 수익: 보유기간별 누적 수취 − 수수료
    print("\n  ══ ③ 보유기간별 실현 수익 (상위 5종목 평균) ══")
    print(f"  {'보유':<10}{'누적수취':>11}{'수수료':>10}{'순수익':>10}{'월환산':>10}")
    for hold in (3, 9, 21, 45):
        gains = []
        for t0 in starts[::3]:
            cur = sorted(((abs(hist[s].get(t0, 0)), s) for s in hist if t0 in hist[s]), reverse=True)[:TOPN]
            for _, s in cur:
                d0 = hist[s].get(t0)
                if d0 is None:
                    continue
                tot = 0.0
                for k in range(hold):
                    d = hist[s].get(t0 + k)
                    if d is None:
                        continue
                    tot += d if d0 > 0 else -d
                gains.append(tot)
        if not gains:
            continue
        g = statistics.mean(gains)
        net = g - FEE_ROUNDTRIP
        days = hold * 8 / 24
        print(f"  {days:>5.0f}일{g*100:>11.3f}%{FEE_ROUNDTRIP*100:>9.3f}%{net*100:>9.3f}%{net*100*30/days:>9.2f}%")

    await bn.close(); await ok.close()


if __name__ == "__main__":
    asyncio.run(main())
