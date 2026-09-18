#!/usr/bin/env python3
"""idle_zone_fix.py — '중간 지대'에서 안 걸리는 문제를 어떤 배정이 푸는가.

mooja 질문: 올라도 안 걸리고 내려도 안 걸리는 구간에서 고수익을 내려면.

문제의 구조
  55일 채널 돌파는 **끝단**에서만 신호가 난다. 고가까지 +23.5%, 저가까지 −25.7%인
  지금 같은 중간 지대에서는 양쪽 다 미달이라 몇 주씩 빈다(실측: BULL 240일 중 167일 무신호).

그래서 무엇을 재는가
  국면 배정(REGIME_STRATEGY_MAP)만 바꿔가며 **활동량과 수익을 함께** 본다.
  활동량만 늘리면 수수료로 죽고, 수익만 보면 몇 주씩 비는 걸 못 잡는다.

  · 무포지션 일수 / 최장 공백  — 중간 지대 문제가 실제로 풀렸는지
  · 시드 12회 로그수익 분포     — 운이 아니라 구조인지 (중앙값과 하위 10%)
  · MDD                        — 활동량을 늘린 대가

한계
  일봉·수수료 미반영 백테스트다. 실거래는 왕복 비용이 붙는다(8401 실측: 거래 87건 중
  61%가 비용을 못 넘겼다). 그래서 **거래 수가 늘어난 안은 비용에 더 취약하다** —
  여기 수치는 상한이지 예상치가 아니다.
"""
import json
import random
import statistics as stx
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/l/project/8888/lab")
import regime_map_backtest as B

CACHE = "/Users/l/project/8888/lab/_universe_cache.json"
BOT = sys.argv[1] if len(sys.argv) > 1 else "8401"
DAYS = 730
SEEDS = 12

# 국면 배정 후보. 현행을 맨 위에 둔다.
MAPS = [
    ("현행  BULL:DonVol  BEAR:DualBB  RANGE:DonVol",
     {"BULL": "DonchianVol", "BEAR": "DualBB", "RANGE": "DonchianVol"}),
    ("① BULL만 DualBB",
     {"BULL": "DualBB", "BEAR": "DualBB", "RANGE": "DonchianVol"}),
    ("② RANGE만 DualBB",
     {"BULL": "DonchianVol", "BEAR": "DualBB", "RANGE": "DualBB"}),
    ("③ 전부 DualBB",
     {"BULL": "DualBB", "BEAR": "DualBB", "RANGE": "DualBB"}),
    ("④ BULL 거래량필터 해제(Donchian)",
     {"BULL": "Donchian", "BEAR": "DualBB", "RANGE": "Donchian"}),
]


def load():
    raw = json.load(open(CACHE))
    cfg = json.load(open(f"/Users/l/project/{BOT}/config.json", encoding="utf-8"))
    wl = cfg["SYMBOL_WHITELIST"]
    data = {s: pd.DataFrame(raw[s], columns=["ts", "open", "high", "low", "close", "volume"])
            for s in wl if s in raw}
    btc = pd.DataFrame(raw["BTC/USDT:USDT"],
                       columns=["ts", "open", "high", "low", "close", "volume"])
    b = btc.copy()
    b["ma"] = b["close"].rolling(B.MA_LEN).mean()
    b["adx"] = B._adx(b, 14)
    b["day"] = pd.to_datetime(b["ts"], unit="ms").dt.strftime("%Y-%m-%d")
    b = b.dropna(subset=["ma", "adx"])
    rr = np.where(b["adx"] < B.ADX_TH, "RANGE",
                  np.where(b["close"] > b["ma"], "BULL", "BEAR"))
    dl = list(b["day"])
    reg = {dl[i + 1]: rr[i] for i in range(len(dl) - 1)}
    days = [d for d in dl if d in reg][-DAYS:]
    return data, reg, days


def idle_days(data, reg, days, smap, seed):
    """무포지션 일수와 최장 공백. 신호는 그대로 두고 보유만 센다."""
    rng = random.Random(seed)
    need = set(smap.values()) - {"관망"}
    sig, atr, idx = {}, {}, {}
    for s, df in data.items():
        atr[s] = B._atr(df, 14).values
        idx[s] = {int(t): i for i, t in enumerate(df["ts"].values)}
        sig[s] = {n: B.SIGGEN[n](df) for n in need}

    open_pos, occ = [], []
    for day in days:
        ts = int(pd.Timestamp(day).timestamp() * 1000)
        still = []
        for p in open_pos:
            i = idx[p["sym"]].get(ts)
            if i is None:
                still.append(p)
                continue
            df = data[p["sym"]]
            hi, lo = float(df["high"].iloc[i]), float(df["low"].iloc[i])
            hit = ((lo <= p["sl"]) if p["dir"] > 0 else (hi >= p["sl"])) or \
                  ((hi >= p["tp"]) if p["dir"] > 0 else (lo <= p["tp"]))
            if not hit:
                still.append(p)
        open_pos = still

        st = smap.get(reg.get(day), "관망")
        if st not in ("관망", None, "") and len(open_pos) < B.MAX_POS:
            held = {p["sym"] for p in open_pos}
            cands = []
            for s, df in data.items():
                if s in held:
                    continue
                i = idx[s].get(ts)
                if i is None or i < 1:
                    continue
                d = int(sig[s][st][i - 1])
                if d == 0:
                    continue
                a = float(atr[s][i - 1])
                op = float(df["open"].iloc[i])
                if not np.isfinite(a) or a <= 0 or op <= 0:
                    continue
                cands.append((s, d, op, a))
            cands.sort()
            rng.shuffle(cands)
            for s, d, op, a in cands[: B.MAX_POS - len(open_pos)]:
                slp = (a * B.SL_ATR) / op
                tpp = (a * B.TP_ATR) / op
                open_pos.append({"sym": s, "dir": d,
                                 "sl": op * (1 - d * slp), "tp": op * (1 + d * tpp)})
        occ.append(len(open_pos))

    zero = sum(1 for x in occ if x == 0)
    run = mx = 0
    for x in occ:
        run = run + 1 if x == 0 else 0
        mx = max(mx, run)
    return zero, mx


def main():
    data, reg, days = load()
    print(f"\n{'='*104}")
    print(f"  {BOT} — 중간 지대 해법 비교   {days[0]} ~ {days[-1]} ({len(days)}일)")
    print(f"  {len(data)}종목 · 동시보유 {B.MAX_POS} · 시드 {SEEDS}회 · SL/TP = ATR {B.SL_ATR}/{B.TP_ATR}")
    print(f"{'='*104}\n")
    print(f"  {'배정':44}{'거래':>6}{'무포지션':>9}{'최장공백':>9}"
          f"{'로그중앙':>9}{'하위10%':>9}{'MDD':>7}")
    print("  " + "─" * 100)

    rows = []
    for name, smap in MAPS:
        seeds = [B.stats(*B.simulate(data, reg, smap, days, rng=random.Random(sd)), days)
                 for sd in range(SEEDS)]
        logs = sorted(s["tlog"] for s in seeds)
        med = logs[len(logs) // 2]
        p10 = logs[max(0, int(len(logs) * 0.10))]
        base = B.stats(*B.simulate(data, reg, smap, days), days)
        z, g = idle_days(data, reg, days, smap, 0)
        rows.append(dict(name=name, n=base["n"], zero=z, gap=g,
                         med=med, p10=p10, mdd=base["mdd"]))
        print(f"  {name:44}{base['n']:>6}{z:>8}일{g:>8}일"
              f"{med:>9.2f}{p10:>9.2f}{base['mdd']*100:>6.0f}%")

    print("  " + "─" * 100)
    cur = rows[0]
    print(f"\n{'='*104}\n  현행 대비\n{'='*104}")
    for r in rows[1:]:
        dz = r["zero"] - cur["zero"]
        dm = r["med"] - cur["med"]
        dp = r["p10"] - cur["p10"]
        verdict = "✅ 활동량·수익 모두 개선" if (dz < 0 and dm > 0 and dp > 0) else \
                  "△ 활동량만 개선" if dz < 0 else "❌ 개선 없음"
        print(f"    {r['name']:44} 무포지션 {dz:+4}일 · 로그중앙 {dm:+.2f} · "
              f"하위10% {dp:+.2f}   {verdict}")
    print(f"\n  ⚠️ 수수료 미반영이다. 거래가 늘어난 안일수록 실거래에서 더 깎인다.")
    print(f"     8401 실측: 거래 87건 중 61%가 왕복 비용을 못 넘겼다.")
    print(f"{'='*104}\n")


if __name__ == "__main__":
    main()
