#!/usr/bin/env python3
"""gap_decomposition.py — 무포지션 공백은 '신호가 드물어서'인가 '너무 빨리 나와서'인가.

mooja 질문: 둘 중 뭐가 더 크냐.

가르는 법
  신호 발생은 **그대로 두고**, 보유 모형만 바꿔 무포지션 일수를 비교한다.

    ① 당일청산  — 진입한 봉 안에서 청산(실측: 8401 보유시간 중앙 1.6시간)
    ② 캡 8%     — SL = min(ATR×2, 8%), TP는 같은 비율로 축소 (**현재 설정**)
    ③ 설계      — SL = ATR×2, TP = ATR×4, 캡 없음

  ③의 공백 = **신호가 드물어서 생긴 공백** (보유를 최대로 해도 남는 것)
  ①의 공백 − ③의 공백 = **조기청산이 추가로 만든 공백**

한계를 먼저 적는다
  · 일봉 시뮬이라 '1.6시간 보유'를 **'진입한 봉 안에서 청산'**으로 근사했다.
    실제보다 보유를 길게 잡은 셈이므로, 조기청산의 기여는 **과소평가**된다.
  · 진입가는 다음 봉 시가, 청산은 고가/저가 접촉. 한 봉에 둘 다면 SL 우선.
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
SEEDS = 8


def load():
    raw = json.load(open(CACHE))
    cfg = json.load(open(f"/Users/l/project/{BOT}/config.json", encoding="utf-8"))
    wl = cfg["SYMBOL_WHITELIST"]
    data = {s: pd.DataFrame(raw[s], columns=["ts", "open", "high", "low", "close", "volume"])
            for s in wl if s in raw}
    btc = pd.DataFrame(raw["BTC/USDT:USDT"],
                       columns=["ts", "open", "high", "low", "close", "volume"])
    b = btc.copy()
    b["ma"] = b["close"].rolling(200).mean()
    b["adx"] = B._adx(b, 14)
    b["day"] = pd.to_datetime(b["ts"], unit="ms").dt.strftime("%Y-%m-%d")
    b = b.dropna(subset=["ma", "adx"])
    th = float(cfg.get("REGIME_ADX_THRESHOLD") or 20.0)
    rr = np.where(b["adx"] < th, "RANGE", np.where(b["close"] > b["ma"], "BULL", "BEAR"))
    dl = list(b["day"])
    reg = {dl[i + 1]: rr[i] for i in range(len(dl) - 1)}
    days = [d for d in dl if d in reg][-DAYS:]
    smap = cfg.get("REGIME_STRATEGY_MAP") or {
        "BULL": "DonchianVol", "BEAR": "DualBB", "RANGE": "DonchianVol"}
    return cfg, data, reg, days, smap


def run(mode, data, reg, days, smap, cfg, seed, maxpos):
    """mode: 'sameday' | 'cap' | 'design'"""
    rng = random.Random(seed)
    cap = float(cfg.get("DYNAMIC_SL_CAP_PCT") or 0.08)
    need = set(smap.values()) - {"관망"}
    sig, atr, idx = {}, {}, {}
    for s, df in data.items():
        atr[s] = B._atr(df, 14).values
        idx[s] = {int(t): i for i, t in enumerate(df["ts"].values)}
        sig[s] = {n: B.SIGGEN[n](df) for n in need}

    open_pos, occ = [], []
    for day in days:
        r = reg.get(day)
        ts = int(pd.Timestamp(day).timestamp() * 1000)

        still = []
        for p in open_pos:
            df = data[p["sym"]]
            i = idx[p["sym"]].get(ts)
            if i is None:
                still.append(p)
                continue
            hi, lo = float(df["high"].iloc[i]), float(df["low"].iloc[i])
            hit = ((lo <= p["sl"]) if p["dir"] > 0 else (hi >= p["sl"])) or \
                  ((hi >= p["tp"]) if p["dir"] > 0 else (lo <= p["tp"]))
            if not hit:
                still.append(p)
        open_pos = still

        st = smap.get(r, "관망")
        if st not in ("관망", None, "") and len(open_pos) < maxpos:
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
            for s, d, op, a in cands[: maxpos - len(open_pos)]:
                sl_pct = (a * B.SL_ATR) / op
                tp_pct = (a * B.TP_ATR) / op
                if mode == "cap" and cap > 0 and sl_pct > cap:
                    ratio = cap / sl_pct
                    sl_pct, tp_pct = cap, tp_pct * ratio
                open_pos.append({"sym": s, "dir": d,
                                 "sl": op * (1 - d * sl_pct),
                                 "tp": op * (1 + d * tp_pct)})

        occ.append(len(open_pos))

        # 당일청산 모형 — 진입한 봉 안에서 전부 닫는다(실측 1.6시간 근사)
        if mode == "sameday":
            open_pos = []

    zero = sum(1 for x in occ if x == 0)
    run_ = mx = 0
    for x in occ:
        if x == 0:
            run_ += 1
            mx = max(mx, run_)
        else:
            run_ = 0
    return dict(zero=zero, pct=(len(occ) - zero) / len(occ) * 100, maxgap=mx)


def main():
    cfg, data, reg, days, smap = load()
    maxpos = int(cfg.get("MAX_POSITIONS", 3))
    print(f"\n{'='*88}")
    print(f"  {BOT} — 무포지션 공백 분해   {days[0]} ~ {days[-1]} ({len(days)}일)")
    print(f"  {len(data)}종목 · 동시보유 {maxpos} · 국면배정 {smap}")
    print(f"  SL 캡 {float(cfg.get('DYNAMIC_SL_CAP_PCT') or 0.08)*100:.0f}%")
    print(f"{'='*88}\n")

    MODES = [
        ("① 당일청산 (실측 1.6h 근사)", "sameday"),
        ("② 캡 8% — 현재 설정",         "cap"),
        ("③ 설계 ATR 2:4 (캡 없음)",    "design"),
    ]
    res = {}
    print(f"  {'보유 모형':30}{'보유율':>9}{'무포지션 일수':>14}{'최장 공백':>12}")
    print("  " + "─" * 68)
    for name, m in MODES:
        rs = [run(m, data, reg, days, smap, cfg, sd, maxpos) for sd in range(SEEDS)]
        z = stx.median(r["zero"] for r in rs)
        p = stx.median(r["pct"] for r in rs)
        g = stx.median(r["maxgap"] for r in rs)
        res[m] = (z, p, g)
        print(f"  {name:30}{p:>8.0f}%{z:>12.0f}일{g:>10.0f}일")

    z1, _, g1 = res["sameday"]
    z2, _, g2 = res["cap"]
    z3, _, g3 = res["design"]
    print("  " + "─" * 68)
    print(f"\n{'='*88}\n  분해\n{'='*88}")
    print(f"  신호가 드물어서 생긴 공백        {z3:>6.0f}일   (보유를 최대로 늘려도 남는 것)")
    print(f"  조기청산이 **추가로** 만든 공백   {z1-z3:>6.0f}일   (당일청산 {z1:.0f} − 설계 {z3:.0f})")
    tot = z1 if z1 > 0 else 1
    print(f"\n  기여도:  신호 드묾 {z3/tot*100:>4.0f}%   ·   조기청산 {(z1-z3)/tot*100:>4.0f}%")
    print(f"\n  현재 설정(캡 8%)의 공백은 {z2:.0f}일 — 설계({z3:.0f}일)보다 {z2-z3:+.0f}일 많다")
    print(f"  최장 공백:  당일청산 {g1:.0f}일 · 캡8% {g2:.0f}일 · 설계 {g3:.0f}일")
    print(f"\n  ⚠️ 일봉 시뮬이라 '1.6시간'을 '진입한 봉 안 청산'으로 근사했다.")
    print(f"     실제보다 보유를 **길게** 잡았으므로 조기청산 기여는 과소평가된 값이다.")
    print(f"{'='*88}\n")


if __name__ == "__main__":
    main()
