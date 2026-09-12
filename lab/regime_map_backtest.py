#!/usr/bin/env python3
"""regime_map_backtest.py — REGIME_STRATEGY_MAP의 BEAR·RANGE 칸을 검증한다.

지금 8401·8402·8410은 이렇게 설정돼 있다.

    {"BULL": "DonchianVol", "BEAR": "관망", "RANGE": "관망"}

최근 BTC 국면 분포가 BEAR 48% · RANGE 30% · BULL 22%이므로 **1년의 78%를
손 놓고 있다.** 이 칸을 채우면 나아지는지, 아니면 지금이 옳은지를 잰다.

검증 규율 ([[backtest-sample-window]] · [[structural-edge-rejections]])
  · 표본 2년. 7개월은 국면 운을 엣지로 오인한다.
  · **4분할 전부 같은 부호**여야 채택한다. 한 분기라도 뒤집히면 기각.
  · MAX_POSITIONS 상한과 비용을 반영한다. 무제한 동시보유는 허구다.
  · 최고점 대비 낙폭(MDD)을 같이 본다. 수익만 보면 파산 경로를 못 본다.
  · 인접값 안정성 — 채택안이 이웃 설정과 크게 다르면 과최적화다.

체결 모형
  신호는 **닫힌 일봉 종가**에서 나고 진입은 **다음 봉 시가**다(봇과 동일).
  청산은 그 다음 봉부터 고가/저가가 SL·TP에 닿는지로 판정하며,
  한 봉에서 둘 다 닿으면 **SL 우선**(보수적)으로 본다.
  비용은 왕복 테이커 0.10% + 슬리피지 0.05% = 명목가 0.15%.
"""
import asyncio
import json
import os
import sys
import datetime as dt

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_regime_cache.json")

LEVERAGE = 3.0
MAX_POS = 3
COST_PCT = 0.0015          # 왕복 명목가 대비
SL_ATR, TP_ATR = 2.0, 4.0
DON_LEN, DON_VOL_LEN, DON_VOL_MULT = 55, 20, 1.5
DBB_LEN, DBB_K1, DBB_K2 = 20, 1.0, 2.0
ADX_TH, MA_LEN = 20.0, 200
YEARS = 2


# ═══════════════════════ 지표 ═══════════════════════
def _atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


# ═══════════════════════ 데이터 ═══════════════════════
async def fetch_all(symbols, need):
    import ccxt.async_support as ccxt
    ex = ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    out = {}
    try:
        for s in symbols:
            rows, since = [], None
            # OKX는 한 번에 100봉까지라 과거로 거슬러 올라가며 이어붙인다.
            cur = None
            for _ in range(20):
                try:
                    r = await ex.fetch_ohlcv(s, "1d", limit=100,
                                             params={"before": ""} if cur is None else {"after": str(cur)})
                except Exception as e:
                    print(f"  {s} 조회 실패: {str(e)[:60]}")
                    break
                if not r:
                    break
                rows = r + rows
                cur = r[0][0]
                if len(rows) >= need:
                    break
            if len(rows) < 300:
                print(f"  {s} 데이터 부족 {len(rows)}봉 — 제외")
                continue
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
            df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
            out[s] = df.values.tolist()
            print(f"  {s:22} {len(df)}봉  {pd.to_datetime(df['ts'].iloc[0], unit='ms').date()} ~")
    finally:
        await ex.close()
    return out


def load_data(symbols, need):
    if os.path.exists(CACHE):
        raw = json.load(open(CACHE))
        if all(s in raw for s in symbols):
            print(f"캐시 사용: {CACHE}")
            return {s: pd.DataFrame(raw[s], columns=["ts", "open", "high", "low", "close", "volume"])
                    for s in symbols if s in raw}
    print("거래소에서 일봉 수집 중...")
    raw = asyncio.run(fetch_all(symbols, need))
    json.dump(raw, open(CACHE, "w"))
    return {s: pd.DataFrame(v, columns=["ts", "open", "high", "low", "close", "volume"])
            for s, v in raw.items()}


# ═══════════════════════ 신호 ═══════════════════════
def signals_donchian(df, require_vol):
    """반환: +1(롱) / -1(숏) / 0 — 해당 봉 종가에서 발생한 신호."""
    hi = df["high"].rolling(DON_LEN).max().shift(1)
    lo = df["low"].rolling(DON_LEN).min().shift(1)
    up = df["close"] > hi
    dn = df["close"] < lo
    if require_vol:
        vm = df["volume"].rolling(DON_VOL_LEN).mean()
        vok = df["volume"] > vm * DON_VOL_MULT
        up, dn = up & vok, dn & vok
    return np.where(up, 1, np.where(dn, -1, 0))


def signals_dualbb(df):
    c = df["close"]
    mid = c.rolling(DBB_LEN).mean()
    sd = c.rolling(DBB_LEN).std()
    u1, u2 = mid + DBB_K1 * sd, mid + DBB_K2 * sd
    l1, l2 = mid - DBB_K1 * sd, mid - DBB_K2 * sd
    lng = (c > u1) & (c <= u2)
    sht = (c >= l2) & (c < l1)
    return np.where(lng, 1, np.where(sht, -1, 0))


SIGGEN = {
    "관망": lambda df: np.zeros(len(df), dtype=int),
    "DonchianVol": lambda df: signals_donchian(df, True),
    "Donchian": lambda df: signals_donchian(df, False),
    "DualBB": signals_dualbb,
}


# ═══════════════════════ 시뮬레이션 ═══════════════════════
def simulate(data, btc_reg, smap, days, rng=None):
    """국면별 전략 배정(smap)으로 전 종목을 돌린다. 포지션 상한을 지킨다."""
    # 종목별 신호·ATR을 미리 만든다. 국면마다 전략이 달라 전략별로 다 만든다.
    need = set(smap.values()) - {"관망"}
    sig = {}
    atr = {}
    idx = {}
    for s, df in data.items():
        atr[s] = _atr(df, 14).values
        idx[s] = {int(t): i for i, t in enumerate(df["ts"].values)}
        sig[s] = {name: SIGGEN[name](df) for name in need}

    open_pos = []          # [{sym,dir,entry,sl,tp,i_entry}]
    trades = []
    equity = 1.0
    curve = []
    peak, mdd = 1.0, 0.0

    for day in days:
        reg = btc_reg.get(day)
        ts = int(pd.Timestamp(day).timestamp() * 1000)

        # ── ① 보유분 청산 판정 (오늘 봉의 고가/저가) ──
        still = []
        for p in open_pos:
            df = data[p["sym"]]
            i = idx[p["sym"]].get(ts)
            if i is None:
                still.append(p)
                continue
            hi, lo = float(df["high"].iloc[i]), float(df["low"].iloc[i])
            hit_sl = (lo <= p["sl"]) if p["dir"] > 0 else (hi >= p["sl"])
            hit_tp = (hi >= p["tp"]) if p["dir"] > 0 else (lo <= p["tp"])
            px = None
            if hit_sl:
                px, kind = p["sl"], "SL"      # 한 봉에 둘 다면 SL 우선
            elif hit_tp:
                px, kind = p["tp"], "TP"
            if px is None:
                still.append(p)
                continue
            move = (px / p["entry"] - 1) * p["dir"]
            ret = (move - COST_PCT) * LEVERAGE / MAX_POS
            equity *= (1 + ret)
            trades.append({"sym": p["sym"], "day": day, "dir": p["dir"],
                           "kind": kind, "move": move, "ret": ret,
                           "regime": p["regime"]})
        open_pos = still

        # ── ② 신규 진입 (오늘 시가 = 어제 종가 신호) ──
        strat = smap.get(reg, "관망")
        if strat != "관망" and len(open_pos) < MAX_POS:
            held = {p["sym"] for p in open_pos}
            cands = []
            for s, df in data.items():
                if s in held:
                    continue
                i = idx[s].get(ts)
                if i is None or i < 1:
                    continue
                d = int(sig[s][strat][i - 1])        # 어제 닫힌 봉의 신호
                if d == 0:
                    continue
                a = float(atr[s][i - 1])
                if not np.isfinite(a) or a <= 0:
                    continue
                op = float(df["open"].iloc[i])
                if op <= 0:
                    continue
                cands.append((s, d, op, a))
            # 같은 날 후보가 슬롯보다 많으면 누굴 태울지 정해야 한다.
            # 알파벳순은 앞글자 종목에 쏠려 결과가 그 종목들 운이 된다.
            # 시드로 섞어 여러 번 돌리고 분산을 본다(seed=None이면 알파벳순).
            cands.sort()
            if rng is not None:
                rng.shuffle(cands)
            for s, d, op, a in cands[: MAX_POS - len(open_pos)]:
                open_pos.append({"sym": s, "dir": d, "entry": op,
                                 "sl": op - d * a * SL_ATR,
                                 "tp": op + d * a * TP_ATR,
                                 "regime": reg})

        curve.append((day, equity))
        peak = max(peak, equity)
        mdd = max(mdd, 1 - equity / peak)

    return trades, curve, mdd


def quarters(days, n=4):
    k = len(days) // n
    return [days[i * k:(i + 1) * k if i < n - 1 else len(days)] for i in range(n)]


def qlog(trades, days):
    """분기별 **로그수익** 합. 복리 폭주를 빼고 기여도를 정직하게 본다."""
    out = []
    for q in quarters(days):
        s = set(q)
        out.append(sum(np.log1p(t["ret"]) for t in trades if t["day"] in s))
    return out


def stats(trades, curve, mdd, days):
    tot = (curve[-1][1] - 1) * 100 if curve else 0.0
    n = len(trades)
    wr = len([t for t in trades if t["ret"] > 0]) / n * 100 if n else 0.0
    ql = qlog(trades, days)
    tl = sum(ql)
    # 분기 집중도: 양(+)인 분기 중 가장 큰 것이 전체 로그수익의 몇 %인가
    conc = (max(ql) / tl) if tl > 0 else float("inf")
    return dict(total=tot, n=n, wr=wr, mdd=mdd, ql=ql, tlog=tl,
                conc=conc, all_pos=all(x > 0 for x in ql),
                per_trade=(tl / n if n else 0.0))


def main():
    cfg = json.load(open("/Users/l/project/8401/config.json"))
    syms = cfg["SYMBOL_WHITELIST"]
    need = 365 * YEARS + MA_LEN + 60
    data = load_data(syms + ["BTC/USDT:USDT"], need)
    btc = data.pop("BTC/USDT:USDT", None)
    if btc is None:
        print("BTC 데이터 없음 — 중단")
        return

    # ── BTC 국면 (닫힌 봉 기준) ──
    b = btc.copy()
    b["ma"] = b["close"].rolling(MA_LEN).mean()
    b["adx"] = _adx(b, 14)
    b["day"] = pd.to_datetime(b["ts"], unit="ms").dt.strftime("%Y-%m-%d")
    b = b.dropna(subset=["ma", "adx"])
    # 국면은 '그날 닫힌 봉'으로 정하고 **다음 날** 매매에 쓴다 (미래참조 차단)
    reg_raw = np.where(b["adx"] < ADX_TH, "RANGE",
                       np.where(b["close"] > b["ma"], "BULL", "BEAR"))
    btc_reg = {}
    dlist = list(b["day"])
    for i in range(len(dlist) - 1):
        btc_reg[dlist[i + 1]] = reg_raw[i]

    days = [d for d in dlist if d in btc_reg][-365 * YEARS:]
    days = [d for d in days if d in btc_reg]
    dist = pd.Series([btc_reg[d] for d in days]).value_counts()

    print(f"\n{'='*100}")
    print(f"표본 {days[0]} ~ {days[-1]}  ({len(days)}일) · 종목 {len(data)}개 · "
          f"레버리지 {LEVERAGE:.0f}x · 동시보유 {MAX_POS} · 왕복비용 {COST_PCT*100:.2f}%")
    print("국면 분포: " + " · ".join(f"{k} {v}일({v/len(days)*100:.0f}%)" for k, v in dist.items()))
    print(f"{'='*100}\n")

    base = {"BULL": "DonchianVol", "BEAR": "관망", "RANGE": "관망"}
    cands = [("현행 (BEAR·RANGE 관망)", base)]
    for bear in ["관망", "DualBB", "DonchianVol", "Donchian"]:
        for rng in ["관망", "DonchianVol", "Donchian", "DualBB"]:
            if bear == "관망" and rng == "관망":
                continue
            m = {"BULL": "DonchianVol", "BEAR": bear, "RANGE": rng}
            cands.append((f"BEAR={bear:12} RANGE={rng}", m))

    import random

    half = sorted(data)
    grpA = {k: data[k] for k in half[0::2]}
    grpB = {k: data[k] for k in half[1::2]}

    print("  강건성 4관문 — 하나라도 못 넘으면 기각한다")
    print("    ① 4분할 전부 양수     ② 한 분기 기여도 ≤ 60%")
    print("    ③ 종목 2분할 둘 다 양수 ④ 선택순서 시드 12회 중 하위 25%도 양수\n")
    print(f"  {'배정':34} {'총수익':>10} {'거래':>5} {'승률':>6} {'MDD':>6} "
          f"{'분기집중':>8}  {'①②③④':6} 4분할(로그)")
    print("  " + "─" * 118)

    res = []
    for name, m in cands:
        tr, cv, mdd = simulate(data, btc_reg, m, days)
        st = stats(tr, cv, mdd, days)

        # ③ 종목 2분할
        sa = stats(*simulate(grpA, btc_reg, m, days), days)
        sb = stats(*simulate(grpB, btc_reg, m, days), days)
        g3 = sa["tlog"] > 0 and sb["tlog"] > 0

        # ④ 선택순서 시드 분산
        seeds = []
        for sd in range(12):
            t2, c2, d2 = simulate(data, btc_reg, m, days, rng=random.Random(sd))
            seeds.append(stats(t2, c2, d2, days)["tlog"])
        seeds.sort()
        q25 = seeds[len(seeds) // 4]

        g1 = st["all_pos"]
        g2 = st["conc"] <= 0.60
        g4 = q25 > 0
        gates = "".join("✅" if g else "❌" for g in (g1, g2, g3, g4))
        passed = g1 and g2 and g3 and g4
        st.update(name=name, map=m, g=(g1, g2, g3, g4), passed=passed,
                  seed_med=seeds[len(seeds) // 2], seed_q25=q25, seed_min=seeds[0])
        res.append(st)
        print(f"  {name:34} {st['total']:+9.1f}% {st['n']:5} {st['wr']:5.1f}% "
              f"{st['mdd']*100:5.1f}% {st['conc']*100:7.0f}%  {gates}  [" +
              " ".join(f"{x:+5.2f}" for x in st["ql"]) + "]")

    print(f"\n{'='*100}")
    ok = [r for r in res if r["passed"]]
    print(f"4관문 전부 통과: {len(ok)}개 / {len(res)}개")
    if ok:
        ok.sort(key=lambda r: -r["seed_med"])
        print("\n  ── 통과안 (시드 중앙값 로그수익 순) ──")
        for r in ok:
            print(f"    {r['name']:34} 총 {r['total']:+9.1f}%  MDD {r['mdd']*100:.1f}%  "
                  f"거래 {r['n']}건  시드 중앙 {r['seed_med']:+.2f} / 최악 {r['seed_min']:+.2f}")
    else:
        print("  ❌ 4관문을 통과한 안이 없다 → **현행(관망) 유지가 옳다.**")
    cur = [r for r in res if r["name"].startswith("현행")][0]
    print(f"\n  현행 기준선: 총 {cur['total']:+.1f}% · MDD {cur['mdd']*100:.1f}% · "
          f"거래 {cur['n']}건 · 관문 {''.join('✅' if g else '❌' for g in cur['g'])}")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()
