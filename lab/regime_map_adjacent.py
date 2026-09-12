#!/usr/bin/env python3
"""regime_map_adjacent.py — 채택 후보가 **인접 파라미터에서도 버티는가**.

한 점에서만 좋은 설정은 과최적화다. 파라미터를 한 칸씩 밀었을 때
현행 대비 우위가 유지돼야 진짜다. ([[structural-edge-rejections]])

  DON_LEN        40 / 55 / 70
  DON_VOL_MULT   1.2 / 1.5 / 1.8
  SL·TP 배수     1.5·3 / 2·4 / 2.5·5

각 격자에서 현행(BEAR·RANGE 관망)과 후보들을 같은 조건으로 돌려
**로그수익 차이**를 본다. 절대 수익은 격자마다 달라도 상관없다.
중요한 것은 **부호가 유지되는가**다.
"""
import random
import sys

import numpy as np

sys.path.insert(0, "/Users/l/project/8888/lab")
import regime_map_backtest as B

GRID = []
for dl in (40, 55, 70):
    GRID.append(("DON_LEN", dl))
for vm in (1.2, 1.5, 1.8):
    GRID.append(("DON_VOL_MULT", vm))
for sl, tp in ((1.5, 3.0), (2.0, 4.0), (2.5, 5.0)):
    GRID.append(("SLTP", (sl, tp)))

BASE = {"BULL": "DonchianVol", "BEAR": "관망", "RANGE": "관망"}
CANDS = {
    "BEAR=Donchian RANGE=DonchianVol": {"BULL": "DonchianVol", "BEAR": "Donchian", "RANGE": "DonchianVol"},
    "BEAR=DualBB   RANGE=DonchianVol": {"BULL": "DonchianVol", "BEAR": "DualBB", "RANGE": "DonchianVol"},
    "BEAR=DualBB   RANGE=관망        ": {"BULL": "DonchianVol", "BEAR": "DualBB", "RANGE": "관망"},
}


def set_param(kind, val):
    if kind == "DON_LEN":
        B.DON_LEN = val
    elif kind == "DON_VOL_MULT":
        B.DON_VOL_MULT = val
    elif kind == "SLTP":
        B.SL_ATR, B.TP_ATR = val


def restore():
    B.DON_LEN, B.DON_VOL_MULT, B.SL_ATR, B.TP_ATR = 55, 1.5, 2.0, 4.0


def med_log(data, reg, smap, days, seeds=8):
    out = []
    for sd in range(seeds):
        tr, cv, mdd = B.simulate(data, reg, smap, days, rng=random.Random(sd))
        out.append(B.stats(tr, cv, mdd, days)["tlog"])
    out.sort()
    return out[len(out) // 2]


def main():
    import json
    cfg = json.load(open("/Users/l/project/8401/config.json"))
    syms = cfg["SYMBOL_WHITELIST"]
    data = B.load_data(syms + ["BTC/USDT:USDT"], 365 * B.YEARS + B.MA_LEN + 60)
    btc = data.pop("BTC/USDT:USDT")

    import pandas as pd
    b = btc.copy()
    b["ma"] = b["close"].rolling(B.MA_LEN).mean()
    b["adx"] = B._adx(b, 14)
    b["day"] = pd.to_datetime(b["ts"], unit="ms").dt.strftime("%Y-%m-%d")
    b = b.dropna(subset=["ma", "adx"])
    rr = np.where(b["adx"] < B.ADX_TH, "RANGE",
                  np.where(b["close"] > b["ma"], "BULL", "BEAR"))
    dl = list(b["day"])
    reg = {dl[i + 1]: rr[i] for i in range(len(dl) - 1)}
    days = [d for d in dl if d in reg][-365 * B.YEARS:]

    print(f"\n{'='*104}")
    print("  인접 파라미터 안정성 — 값은 '현행 대비 로그수익 차이' (양수면 현행보다 낫다)")
    print(f"{'='*104}")
    hdr = f"  {'격자':24}" + "".join(f"{k[:30]:>26}" for k in CANDS)
    print(hdr)
    print("  " + "─" * 100)

    tally = {k: [] for k in CANDS}
    for kind, val in GRID:
        # 격자마다 기본값으로 되돌린 뒤 **한 축만** 민다.
        # 안 그러면 앞 격자의 값이 누적돼 서로 다른 조합을 재는 셈이 된다.
        restore()
        set_param(kind, val)
        base = med_log(data, reg, BASE, days)
        row = f"  {kind}={str(val):18}"
        for k, m in CANDS.items():
            d = med_log(data, reg, m, days) - base
            tally[k].append(d)
            row += f"{d:+26.2f}"
        print(row + f"    (현행 {base:+.2f})")
    restore()

    print("  " + "─" * 100)
    print(f"\n{'='*104}")
    print("  판정 — 9개 격자 **전부** 양수여야 채택한다")
    for k, v in tally.items():
        pos = sum(1 for x in v if x > 0)
        ok = pos == len(v)
        print(f"    {'✅' if ok else '❌'} {k}  양수 {pos}/{len(v)}  "
              f"중앙 {np.median(v):+.2f}  최악 {min(v):+.2f}")
    print(f"{'='*104}\n")


if __name__ == "__main__":
    main()
