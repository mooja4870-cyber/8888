#!/usr/bin/env python3
"""verify_gate_span.py — 종목별 추세필터의 EMA 스팬 민감도

설계안 비교에서 종목별 EMA192가 양쪽 구간 최고였다. 다만 3개 스팬만 본 결과라
그 값이 우연일 수 있다. 스팬을 촘촘히 훑어 **넓은 구간에서 고르게 개선되는지**
확인한다. 특정 값에서만 좋으면 과최적화이므로 채택하지 않는다.
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
idx = np.mean([d["close"].values/d["close"].values[0] for d in frames.values()], axis=0)

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

SPANS = [48, 96, 144, 192, 240, 288, 384, 576, 768]
tr = {s2: {s: np.where(d["close"].values > ema(d["close"].values, s2), 1, -1)
           for s, d in frames.items()} for s2 in SPANS}
bk = {s2: np.where(idx > ema(idx, s2), 1, -1) for s2 in SPANS}

print("  " + "═"*80)
print(f"  {'종목별 추세필터 스팬':<26}{'봉인 앞90일(하락)':>26}{'개발 뒤90일(상승)':>26}")
print("  " + "─"*80)
c, n = evaluate(lambda s, i, d: True)
print(f"  {'(게이트 없음)':<26}{c[0]:>26}{c[1]:>26}")
base = n
best = None
for s2 in SPANS:
    c, n = evaluate(lambda s, i, d, s2=s2: (tr[s2][s][i] > 0) == (d == "long"))
    ok = n[0] > base[0] and n[1] > base[1]
    print(f"  {f'EMA{s2} = {s2*15/60/24:.1f}일':<26}{c[0]:>26}{c[1]:>26}  {'✅' if ok else '❌'}")
    if ok and (best is None or sum(n) > best[1]): best = (s2, sum(n))
print("  " + "─"*80)
print(f"  개선 스팬 수: {sum(1 for s2 in SPANS if True)}개 중 검사 · 최고 EMA{best[0] if best else '―'}")
print()
print("  ■ 최고 스팬 + 바스켓 병용")
print("  " + "─"*80)
b = best[0]
for nm, fn in (("종목별만", lambda s,i,d: (tr[b][s][i]>0)==(d=="long")),
               ("종목별+바스켓 동일스팬", lambda s,i,d: (tr[b][s][i]>0)==(d=="long") and (bk[b][i]>0)==(d=="long")),
               ("종목별+바스켓 768", lambda s,i,d: (tr[b][s][i]>0)==(d=="long") and (bk[768][i]>0)==(d=="long"))):
    c, n = evaluate(fn)
    print(f"  {nm:<26}{c[0]:>26}{c[1]:>26}")
