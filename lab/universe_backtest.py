#!/usr/bin/env python3
"""universe_backtest.py — 화이트리스트를 넓히면 정말 버는가.

동기 (2026-09-12): 09-09~09-11 사흘간 시장은 돌파 8건을 냈는데 **전부
화이트리스트 밖**이었다. 넓히면 진입은 는다. 문제는 **버느냐**다.
거래당 총이익 중앙값이 이미 음수라(v11.0.85) 거래를 늘리면 손실만 늘 수도 있다.

비교 종목군
  A 현행 33종목          B 거래대금 상위 60      C 상위 120      D 상위 200 ∪ 현행

전략·체결 모형은 `regime_map_backtest.py`를 그대로 쓴다(국면 라우터 · 동시보유 3 ·
3배 · 다음 봉 시가 진입 · SL 우선). 종목군만 바꿔 **같은 자로** 잰다.

⚠️ 생존편향을 반드시 읽을 것
  '오늘의 거래대금 상위'는 **살아남아 커진 종목들**이다. 2년 전에 그 목록을 알 수
  없었다. 상장폐지·소멸한 종목은 아예 빠져 있다. 그래서 넓은 종목군의 성과는
  **구조적으로 부풀려진다.** 이 편향은 제거할 수 없으므로, 넓은 쪽이 이기더라도
  **큰 폭으로 이기지 않으면 채택하지 않는다.**

⚠️ 비용도 다르게 매긴다
  소형주는 스프레드·슬리피지가 대형 알트와 다르다. 넓은 종목군에는 **왕복 0.30%**
  (현행 가정의 2배)를 매겨 불리하게 잡는다. 그러고도 이겨야 진짜다.
"""
import asyncio
import datetime as dt
import json
import os
import random
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
import regime_map_backtest as B

CACHE = "/Users/l/project/8888/lab/_universe_cache.json"
YEARS = 2
NEED_BARS = 365 * YEARS + 200 + 40      # 2년 + 200MA + 여유
MAP = {"BULL": "DonchianVol", "BEAR": "DualBB", "RANGE": "DonchianVol"}


async def build_universe():
    import ccxt.async_support as ccxt
    ex = ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    try:
        await ex.load_markets()
        tk = await ex.fetch_tickers()
        rank = sorted([(s, float(t.get("quoteVolume") or 0)) for s, t in tk.items()
                       if s.endswith("/USDT:USDT") and ex.market(s).get("swap")],
                      key=lambda x: -x[1])
        top = [s for s, _ in rank]
    finally:
        await ex.close()
    wl = json.load(open("/Users/l/project/8401/config.json", encoding="utf-8"))["SYMBOL_WHITELIST"]
    uni = {
        "A 현행 33종목": list(wl),
        "B 상위 60": top[:60],
        "C 상위 120": top[:120],
        "D 상위 200 ∪ 현행": top[:200] + [s for s in wl if s not in top[:200]],
    }
    allsym = sorted({s for v in uni.values() for s in v} | {"BTC/USDT:USDT"})
    return uni, allsym


async def fetch(symbols):
    import ccxt.async_support as ccxt
    ex = ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    out = {}
    try:
        for i, s in enumerate(symbols):
            rows, cur = [], None
            for _ in range(12):
                try:
                    r = await ex.fetch_ohlcv(s, "1d", limit=100,
                                             params={} if cur is None else {"after": str(cur)})
                except Exception:
                    break
                if not r:
                    break
                rows = r + rows
                cur = r[0][0]
                if len(rows) >= NEED_BARS:
                    break
            if len(rows) < 300:
                continue
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
            df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
            out[s] = df.values.tolist()
            if (i + 1) % 25 == 0:
                print(f"    {i+1}/{len(symbols)} 수집…", flush=True)
    finally:
        await ex.close()
    return out


def load(symbols):
    raw = {}
    if os.path.exists(CACHE):
        raw = json.load(open(CACHE))
    miss = [s for s in symbols if s not in raw]
    if miss:
        print(f"  거래소에서 {len(miss)}종목 수집 중… (캐시 {len(raw)}종목 보유)")
        raw.update(asyncio.run(fetch(miss)))
        json.dump(raw, open(CACHE, "w"))
    return {s: pd.DataFrame(raw[s], columns=["ts", "open", "high", "low", "close", "volume"])
            for s in symbols if s in raw}


def run_case(name, data, reg, days, cost, label):
    B.COST_PCT = cost
    tr, cv, mdd = B.simulate(data, reg, MAP, days)
    st = B.stats(tr, cv, mdd, days)

    ks = sorted(data)
    ga = {k: data[k] for k in ks[0::2]}
    gb = {k: data[k] for k in ks[1::2]}
    sa = B.stats(*B.simulate(ga, reg, MAP, days), days)
    sb = B.stats(*B.simulate(gb, reg, MAP, days), days)
    g3 = sa["tlog"] > 0 and sb["tlog"] > 0

    seeds = sorted(B.stats(*B.simulate(data, reg, MAP, days, rng=random.Random(sd)), days)["tlog"]
                   for sd in range(12))
    q25 = seeds[len(seeds) // 4]

    g1, g2, g4 = st["all_pos"], st["conc"] <= 0.60, q25 > 0
    gates = "".join("✅" if g else "❌" for g in (g1, g2, g3, g4))
    print(f"  {name:20}{label:9}{len(data):>5}종목{st['n']:>6}건{st['total']:>+10.1f}%"
          f"{st['wr']:>7.1f}%{st['mdd']*100:>7.1f}%{st['conc']*100:>7.0f}%  {gates}"
          f"  시드중앙 {seeds[len(seeds)//2]:+.2f} 최악 {seeds[0]:+.2f}")
    return dict(name=name, label=label, n=st["n"], total=st["total"], mdd=st["mdd"],
                passed=all((g1, g2, g3, g4)), med=seeds[len(seeds) // 2], worst=seeds[0],
                nsym=len(data))


def main():
    print(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "  종목군 확대 검증\n")
    uni, allsym = asyncio.run(build_universe())
    data_all = load(allsym)
    btc = data_all.get("BTC/USDT:USDT")
    if btc is None:
        print("BTC 없음 — 중단")
        return

    b = btc.copy()
    b["ma"] = b["close"].rolling(B.MA_LEN).mean()
    b["adx"] = B._adx(b, 14)
    b["day"] = pd.to_datetime(b["ts"], unit="ms").dt.strftime("%Y-%m-%d")
    b = b.dropna(subset=["ma", "adx"])
    rr = np.where(b["adx"] < B.ADX_TH, "RANGE", np.where(b["close"] > b["ma"], "BULL", "BEAR"))
    dl = list(b["day"])
    reg = {dl[i + 1]: rr[i] for i in range(len(dl) - 1)}
    days = [d for d in dl if d in reg][-365 * YEARS:]
    start = days[0]

    print(f"\n  표본 {days[0]} ~ {days[-1]} ({len(days)}일) · 레버리지 3x · 동시보유 3")
    print(f"  국면 배정 {MAP}")
    print(f"\n  ⚠️ 생존편향 — '오늘의 상위'는 살아남은 종목이다. 넓은 쪽이 조금 이기는 정도로는")
    print(f"     채택하지 않는다. 넓은 종목군에는 왕복비용을 **2배(0.30%)**로 불리하게 매긴다.\n")

    print(f"  {'종목군':20}{'비용':9}{'종목':>7}{'거래':>7}{'총수익':>11}"
          f"{'승률':>8}{'MDD':>8}{'분기집중':>8}  {'①②③④':6}")
    print("  " + "─" * 118)

    res = []
    for name, syms in uni.items():
        sub = {s: d for s, d in data_all.items() if s in syms and s != "BTC/USDT:USDT"}
        # 표본 시작 시점에 이미 존재하던 종목만 — 신규 상장의 초기 급등을 빼기 위함
        sub = {s: d for s, d in sub.items()
               if pd.to_datetime(d["ts"].iloc[0], unit="ms").strftime("%Y-%m-%d") <= start}
        if not sub:
            print(f"  {name:20} 2년 이력 보유 종목 없음 — 제외")
            continue
        res.append(run_case(name, sub, reg, days, 0.0015, "0.15%"))
        if not name.startswith("A"):
            res.append(run_case(name, sub, reg, days, 0.0030, "0.30%"))
    B.COST_PCT = 0.0015

    print("  " + "─" * 118)
    base = next((r for r in res if r["name"].startswith("A")), None)
    print(f"\n{'='*100}")
    ok = [r for r in res if r["passed"]]
    print(f"  4관문 통과: {len(ok)}/{len(res)}")
    if base:
        print(f"  기준선(A 현행·0.15%): 총 {base['total']:+.1f}% · 거래 {base['n']}건 · "
              f"MDD {base['mdd']*100:.1f}% · 시드중앙 {base['med']:+.2f} · "
              f"{'통과' if base['passed'] else '탈락'}")
        print("\n  ── 현행 대비 (시드 중앙값 로그수익 차이) ──")
        for r in res:
            if r is base:
                continue
            d = r["med"] - base["med"]
            print(f"    {r['name']:20} 비용 {r['label']:7} {d:+7.2f}  "
                  f"{'✅ 통과' if r['passed'] else '❌ 탈락'}  "
                  f"(거래 {r['n']}건 · MDD {r['mdd']*100:.0f}% · 최악시드 {r['worst']:+.2f})")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()
