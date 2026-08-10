#!/usr/bin/env python3
"""verify_gate_span_fixed.py — 게이트 미래참조 제거 후 재검증

verify_gate_span.py에서 스팬이 짧을수록 성적이 좋아지는 완전 단조 패턴이 나왔다.
이는 엣지가 아니라 **미래참조**였다.

  신호는 df.iloc[i-800:i]로 만든다 → 마지막 봉은 i-1, 진입가도 close[i-1].
  그런데 게이트는 ema[i]와 close[i]를 봤다 → 진입 시점에 알 수 없는 값.
  스팬이 짧을수록 close[i] 자신의 비중이 커져 "그 봉이 올랐는지"를 미리 아는 셈이 된다.

여기서는 게이트를 i-1로 옮겨 진입 시점에 실제로 알 수 있는 정보만 쓴다.
"""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, "/Users/l/project/8888")
exec(open("/Users/l/project/8888/lab/verify_gate_design.py").read()
     .split("def main():")[0].replace('if __name__', '#'))

frames = load()
n0 = len(next(iter(frames.values()))); mid = n0 // 2
sigs = get_signals(frames)
cfg = dict(json.load(open(f"{BOT}/config.json"))); cfg["USE_BE_GUARD"] = False
ema = lambda a, s: pd.Series(a).ewm(span=s, adjust=False).mean().values

SPANS = [24, 48, 96, 144, 192, 288, 384, 576, 768]
# 진입 시점(i)에 확정된 최신 봉은 i-1이므로 게이트도 i-1에서 읽는다.
tr = {s2: {s: np.where(d["close"].values > ema(d["close"].values, s2), 1, -1)
           for s, d in frames.items()} for s2 in SPANS}

def evaluate(pick):
    cells, nets = [], []
    for lo, hi in ((0, mid), (mid, n0)):
        tot, wins, pnl = 0, 0, 0.0
        for s, df in frames.items():
            sg = [x for x in sigs[s] if lo <= x["i"] < hi and pick(s, x["i"], x["dir"])]
            if not sg: continue
            r = simulate_real(sg, df, cfg)
            tot += r["n"]; wins += r["win"]; pnl += r["net"]
        nets.append(pnl*100)
        cells.append(f"{tot}건 {100*wins/tot if tot else 0:.0f}% {pnl*100:+.1f}%")
    return cells, nets

print("  " + "═"*84)
print(f"  {'설정':<30}{'봉인 앞90일(하락)':>26}{'개발 뒤90일(상승)':>26}")
print("  " + "─"*84)
c, base = evaluate(lambda s, i, d: True)
print(f"  {'(게이트 없음)':<30}{c[0]:>26}{c[1]:>26}")
print("  " + "─"*84)
for lag, tag in ((0, "미래참조(i)"), (1, "정상(i-1)")):
    print(f"  ▸ 게이트 시점 {tag}")
    for s2 in SPANS:
        c, n = evaluate(lambda s, i, d, s2=s2, lag=lag: (tr[s2][s][i-lag] > 0) == (d == "long"))
        ok = n[0] > base[0] and n[1] > base[1]
        print(f"    {f'EMA{s2} = {s2*15/60/24:.2f}일':<28}{c[0]:>26}{c[1]:>26}  {'✅' if ok else '❌'}")
    print()
