#!/usr/bin/env python3
"""when_entry.py — "언제 진입하냐"에 날짜로 답한다.

mooja 질문: 8401·8402·8410은 **언제** 포지션이 잡히나.

방법
  ① 지금 각 종목이 55일 채널 끝단에서 얼마나 떨어져 있는지 잰다.
  ② 과거 2년 동안 **같은 거리에 있던 날들**을 찾아, 그 뒤 N일 안에
     실제로 신호가 났는지 센다. → "며칠 안에 진입할 확률"

  추정이 아니라 **같은 상황의 과거 빈도**다. 미래를 보장하지는 않는다.

한계
  · 일봉 종가 기준. 장중 돌파는 다음 날 종가로 확인된다.
  · 국면(BULL/BEAR/RANGE)이 바뀌면 배정 전략이 바뀌어 조건 자체가 달라진다.
  · 표본은 2년치 한 구간이다. 이번에도 같으리란 보장은 없다.
"""
import json
import statistics as stx
import sys

import numpy as np
import pandas as pd

CACHE = "/Users/l/project/8888/lab/_universe_cache.json"
BOTS = sys.argv[1:] or ["8401", "8402", "8410"]
HORIZONS = (1, 3, 5, 7, 14, 30)
DON, VOL_LEN, VOL_MULT = 55, 20, 1.5


def series(df):
    """돌파 신호와 '채널 끝단까지 거리'를 함께 만든다."""
    d = df.iloc[:-1]                      # 마지막 미완성 봉 제외
    hi = d["high"].rolling(DON).max().shift(1)
    lo = d["low"].rolling(DON).min().shift(1)
    vm = d["volume"].rolling(VOL_LEN).mean()
    vok = d["volume"] > vm * VOL_MULT
    sig = (((d["close"] > hi) | (d["close"] < lo)) & vok).values
    c = d["close"].values
    up = (hi.values / c - 1) * 100         # 롱 발동까지 % (양수면 더 올라야)
    dn = (1 - lo.values / c) * 100         # 숏 발동까지 % (양수면 더 내려야)
    near = np.minimum(np.abs(up), np.abs(dn))
    return sig, near, up, dn


def main():
    raw = json.load(open(CACHE))
    print(f"\n{'=' * 96}")
    print(f"  언제 진입하나 — 과거 2년, 같은 거리에서 며칠 안에 신호가 났나")
    print(f"{'=' * 96}")

    for bot in BOTS:
        cfg = json.load(open(f"/Users/l/project/{bot}/config.json", encoding="utf-8"))
        wl = [s for s in cfg.get("SYMBOL_WHITELIST", []) if s in raw]
        maxpos = int(cfg.get("MAX_POSITIONS", 3))

        cur, hist = [], []
        for s in wl:
            df = pd.DataFrame(raw[s], columns=["ts", "open", "high", "low", "close", "volume"])
            sig, near, up, dn = series(df)
            ok = np.isfinite(near)
            if not ok.any():
                continue
            cur.append((s.split("/")[0], near[-1], up[-1], dn[-1]))
            hist.append((sig, near))

        if not cur:
            print(f"\n  {bot}: 데이터 없음")
            continue

        cur.sort(key=lambda x: x[1])
        nearest = cur[0]
        med = stx.median(x[1] for x in cur)

        print(f"\n  ── {bot} · {len(cur)}종목 · 동시보유 {maxpos} ──")
        print(f"    가장 가까운 종목  {nearest[0]}  {nearest[1]:.2f}% 남음"
              f"   (롱까지 {nearest[2]:+.1f}% / 숏까지 {nearest[3]:+.1f}%)")
        print(f"    전 종목 중앙값    {med:.1f}% 남음")

        # ── 함대 기준 ──
        # 봇은 종목 하나가 아니라 **화이트리스트 전체**를 동시에 본다.
        # 그러니 '어느 한 종목이라도 신호가 났는가'를 날짜 단위로 세야 한다.
        # 상태 비교도 종목 하나가 아니라 **그날의 전 종목 중앙 거리**로 맞춘다.
        L = min(len(s) for s, _ in hist)
        sig_any = np.zeros(L, dtype=bool)
        near_med = np.full(L, np.nan)
        stack = np.full((len(hist), L), np.nan)
        for j, (s, nr) in enumerate(hist):
            sig_any |= s[-L:]
            stack[j] = nr[-L:]
        with np.errstate(all="ignore"):
            near_med = np.nanmedian(stack, axis=0)

        band = max(2.0, med * 0.20)
        lo_b, hi_b = med - band, med + band
        print(f"\n    화이트리스트 **전체** 기준 — 그날 중앙 거리가 {lo_b:.1f}~{hi_b:.1f}%였던 날로부터")
        print(f"      {'기간':>8}{'진입 발생':>12}{'표본':>10}")
        rows = []
        for h in HORIZONS:
            hit = tot = 0
            for i in range(L - h):
                if not np.isfinite(near_med[i]) or not (lo_b <= near_med[i] <= hi_b):
                    continue
                tot += 1
                if sig_any[i + 1:i + 1 + h].any():
                    hit += 1
            rows.append((h, hit, tot))
            pct = hit / tot * 100 if tot else 0
            print(f"      {h:>6}일{pct:>11.0f}%{tot:>10}일")

        base = sig_any.mean() * 100
        print(f"\n    (참고) 2년 전체에서 하루에 신호가 하나라도 난 날: {base:.0f}%")

    print(f"\n{'=' * 96}")
    print("  ※ 과거 같은 거리에서의 실측 빈도다. 예언이 아니다.")
    print("     국면이 바뀌면 배정 전략이 달라져 조건 자체가 변한다.")
    print(f"{'=' * 96}\n")


if __name__ == "__main__":
    main()
