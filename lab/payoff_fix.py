#!/usr/bin/env python3
"""payoff_fix.py — 8401의 손익비를 올리는 방법을 문헌대로 구현해 비교한다.

실측 진단 (거래소 원장 115건)
  승률 36.5% · 손익비 1.73 · 본전 승률 36.6%
  → **정확히 본전선에 걸려 있다.** 기대값 −0.00011/건.

문헌이 지목하는 원인
  · 터틀 System 2는 55일 돌파로 들어가 **20일 반대 채널**로 나온다.
    실제 사례: 11주 보유 +45%, 3개월 +100% — 승리를 길게 끌어 손익비를 만든다.
  · "Exiting too early directly reduces the payoff ratio" — 조기 청산이 손익비를 죽인다.
  · 8401 실측: **115건 전부 보유 1시간 미만.** 진입만 터틀이고 청산은 아니다.
  · 상위 타임프레임 추세 필터가 "가장 큰 단일 레버" — 횡보장 가짜 돌파를 걷어낸다.

그래서 무엇을 비교하나
  ① 현행        SL=ATR×2 / TP=ATR×4 / 캡 8%
  ② 캡 해제     SL=ATR×2 / TP=ATR×4 / 캡 없음
  ③ 터틀 청산   SL=ATR×2 · 익절 없음 · **20일 반대 채널**에 닿으면 청산
  ④ 터틀+필터   ③ + 200일선 위에서만 롱 / 아래에서만 숏
  ⑤ 손익비 1:3  SL=ATR×2 / TP=ATR×6 / 캡 없음

각 안마다 승률·손익비·기대값·월수익률을 낸다. 비용은 실측 왕복 7bp를 뺀다.

한계
  · 일봉 종가 기준. 장중 SL·TP 동시 접촉 시 **SL 우선**(보수적).
  · 표본은 2년 한 구간. 국면 운이 섞인다 — 시드 12회로 분산도 함께 본다.
  · 실거래에서 115건 전부가 1시간 내 청산된 **원인**은 여기서 다루지 않는다.
    이 시뮬은 "설계대로 들고 있었다면"의 상한이다.
"""
import json
import random
import statistics as stx
import sys

import numpy as np
import pandas as pd

CACHE = "/Users/l/project/8888/lab/_universe_cache.json"
BOT = sys.argv[1] if len(sys.argv) > 1 else "8401"
DAYS, SEEDS = 730, 12
DON, VOL_LEN, VOL_MULT = 55, 20, 1.5
EXIT_DON = 20            # 터틀 System 2 청산 채널
COST = 0.0007            # 왕복 7bp (실측: 진입 메이커 2bp + 청산 테이커 5bp)
MA_LEN = 200


def load():
    raw = json.load(open(CACHE))
    cfg = json.load(open(f"/Users/l/project/{BOT}/config.json", encoding="utf-8"))
    data = {}
    for s in cfg["SYMBOL_WHITELIST"]:
        if s not in raw:
            continue
        d = pd.DataFrame(raw[s], columns=["ts", "open", "high", "low", "close", "volume"])
        if len(d) < MA_LEN + DON + 5:
            continue
        data[s] = d
    return data, int(cfg.get("MAX_POSITIONS", 3)), cfg


def prep(df):
    """신호·ATR·청산채널·추세선을 한 번에 만든다."""
    d = df.iloc[:-1].reset_index(drop=True)
    hi = d["high"].rolling(DON).max().shift(1)
    lo = d["low"].rolling(DON).min().shift(1)
    vm = d["volume"].rolling(VOL_LEN).mean()
    vok = d["volume"] > vm * VOL_MULT
    long_sig = ((d["close"] > hi) & vok).values
    short_sig = ((d["close"] < lo) & vok).values
    tr = pd.concat([d["high"] - d["low"],
                    (d["high"] - d["close"].shift()).abs(),
                    (d["low"] - d["close"].shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().values
    return dict(
        open=d["open"].values, high=d["high"].values,
        low=d["low"].values, close=d["close"].values,
        long=long_sig, short=short_sig, atr=atr,
        exit_hi=d["high"].rolling(EXIT_DON).max().shift(1).values,
        exit_lo=d["low"].rolling(EXIT_DON).min().shift(1).values,
        ma=d["close"].rolling(MA_LEN).mean().values,
        ts=d["ts"].values,
    )


def simulate(mode, data, maxpos, seed):
    rng = random.Random(seed)
    P = {s: prep(df) for s, df in data.items()}
    idx = {s: {int(t): i for i, t in enumerate(P[s]["ts"])} for s in P}
    days = sorted({int(t) for s in P for t in P[s]["ts"]})[-DAYS:]

    use_cap = mode in ("cur", "cur_ma")
    use_turtle = mode in ("turtle", "turtle_ma")
    use_ma = mode in ("turtle_ma", "cur_ma", "nocap_ma")
    tp_mult = 6.0 if mode == "rr3" else 4.0

    open_pos, trades = [], []
    for ts in days:
        # ── 청산 ──
        still = []
        for p in open_pos:
            q = P[p["s"]]
            i = idx[p["s"]].get(ts)
            if i is None:
                still.append(p)
                continue
            hi, lo = q["high"][i], q["low"][i]
            out = None
            if p["d"] > 0:
                if lo <= p["sl"]:
                    out = p["sl"]
                elif use_turtle:
                    ex = q["exit_lo"][i]
                    if np.isfinite(ex) and lo <= ex:
                        out = ex
                elif hi >= p["tp"]:
                    out = p["tp"]
            else:
                if hi >= p["sl"]:
                    out = p["sl"]
                elif use_turtle:
                    ex = q["exit_hi"][i]
                    if np.isfinite(ex) and hi >= ex:
                        out = ex
                elif lo <= p["tp"]:
                    out = p["tp"]
            if out is None:
                still.append(p)
            else:
                r = (out / p["e"] - 1) * p["d"] - COST
                trades.append(r)
        open_pos = still

        # ── 진입 ──
        if len(open_pos) < maxpos:
            held = {p["s"] for p in open_pos}
            cand = []
            for s, q in P.items():
                if s in held:
                    continue
                i = idx[s].get(ts)
                if i is None or i < 1:
                    continue
                d = 1 if q["long"][i - 1] else (-1 if q["short"][i - 1] else 0)
                if d == 0:
                    continue
                a, op, ma = q["atr"][i - 1], q["open"][i], q["ma"][i - 1]
                if not (np.isfinite(a) and a > 0 and op > 0):
                    continue
                if use_ma:
                    if not np.isfinite(ma):
                        continue
                    if (d > 0 and op < ma) or (d < 0 and op > ma):
                        continue        # 상위 추세와 반대면 버린다
                cand.append((s, d, op, a))
            cand.sort()
            rng.shuffle(cand)
            for s, d, op, a in cand[: maxpos - len(open_pos)]:
                sl_pct = a * 2.0 / op
                tp_pct = a * tp_mult / op
                if use_cap and sl_pct > 0.08:
                    tp_pct *= 0.08 / sl_pct
                    sl_pct = 0.08
                open_pos.append({"s": s, "d": d, "e": op,
                                 "sl": op * (1 - d * sl_pct),
                                 "tp": op * (1 + d * tp_pct)})
    return trades


def stats(tr):
    if not tr:
        return None
    w = [x for x in tr if x > 0]
    l = [x for x in tr if x <= 0]
    if not w or not l:
        return None
    pw = len(w) / len(tr)
    wa, la = stx.mean(w), stx.mean(l)
    rr = abs(wa / la)
    return dict(n=len(tr), pw=pw, wa=wa, la=la, rr=rr,
                ev=pw * wa + (1 - pw) * la,
                be=1 / (1 + rr))


def main():
    data, maxpos, cfg = load()
    print(f"\n{'=' * 104}")
    print(f"  {BOT} 손익비 개선안 비교 — {len(data)}종목 · 동시보유 {maxpos} · 2년 · 시드 {SEEDS}회")
    print(f"  왕복비용 {COST * 10000:.0f}bp · 진입 55일 돌파+거래량 {VOL_MULT}배")
    print(f"{'=' * 104}\n")
    print(f"  {'안':26}{'거래':>7}{'승률':>8}{'손익비':>8}{'본전승률':>9}"
          f"{'기대값':>10}{'월수익':>9}")
    print("  " + "─" * 88)

    MODES = [
        ("① 현행 ATR2/4 · 캡 8%",      "cur"),
        ("② 캡 해제",                  "nocap"),
        ("③ 터틀 20일채널 청산",        "turtle"),
        ("④ 터틀 + 200일선 필터",       "turtle_ma"),
        ("⑤ 손익비 1:3 (TP×6)",        "rr3"),
        # [2026-09-19 추가] ④는 '터틀 청산'과 '200일선 필터'의 묶음이라
        # 각각의 기여를 알 수 없었다. 필터만 따로 떼어 잰다.
        ("⑥ 현행 + 200일선 필터만",     "cur_ma"),
        ("⑦ 캡해제 + 200일선 필터",     "nocap_ma"),
    ]
    out = []
    for name, mode in MODES:
        alls, evs = [], []
        for sd in range(SEEDS):
            tr = simulate(mode, data, maxpos, sd)
            s = stats(tr)
            if s:
                alls.append(s)
                evs.append(s["ev"])
        if not alls:
            print(f"  {name:26}  거래 없음")
            continue
        m = alls[len(alls) // 2]
        ev = stx.median(evs)
        n = stx.median(s["n"] for s in alls)
        pw = stx.median(s["pw"] for s in alls)
        rr = stx.median(s["rr"] for s in alls)
        # 월 수익률 = 건당 수익률 × 월 거래수 × (명목/증거금 = 레버리지/자리수)
        lev = float(cfg.get("LEVERAGE", 3))
        per_month = n / (DAYS / 30)
        mon = ev * per_month * lev / maxpos * 100
        out.append((name, n, pw, rr, ev, mon, evs))
        print(f"  {name:26}{n:>7.0f}{pw * 100:>7.1f}%{rr:>8.2f}"
              f"{1 / (1 + rr) * 100:>8.1f}%{ev * 100:>9.2f}%{mon:>8.1f}%")

    print("  " + "─" * 88)
    print(f"\n{'=' * 104}\n  판정 (목표 월 4~7%)\n{'=' * 104}")
    for name, n, pw, rr, ev, mon, evs in out:
        lo = min(evs) * (n / (DAYS / 30)) * 3 / maxpos * 100
        ok = "✅ 목표 달성" if mon >= 4 else "△ 흑자·목표 미달" if mon > 0 else "❌ 적자"
        print(f"    {name:26} 월 {mon:+6.1f}%  최악시드 {lo:+6.1f}%   {ok}")
    print(f"\n  ⚠️ 일봉 종가 기준·SL 우선 가정의 **상한**이다. 실거래는 슬리피지가 더 붙는다.")
    print(f"     실측 115건이 전부 1시간 내 청산된 원인은 이 시뮬에 반영되지 않았다.")
    print(f"{'=' * 104}\n")


if __name__ == "__main__":
    main()
