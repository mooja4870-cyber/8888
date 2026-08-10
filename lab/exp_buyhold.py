import numpy as np, pandas as pd
exec(open('/tmp/fund_a.py').read().split("print(f\"  {len(F)}종목")[0])
F=load(); n0=len(next(iter(F.values()))); mid=n0//2
print(f"  {len(F)}종목 · {n0/24:.0f}일")
print("  "+"═"*66)
print(f"  {'구간':<22}{'BTC 보유':>12}{'15종목 균등보유':>18}")
print("  "+"─"*66)
for nm,lo,hi in (('전체 241일',0,n0-1),('봉인(앞 120일)',0,mid),('개발(뒤 120일)',mid,n0-1)):
    b=F['BTC']['close'].values; btc=(b[hi]/b[lo]-1)*100
    eq=np.mean([(d['close'].values[hi]/d['close'].values[lo]-1)*100 for d in F.values()])
    print(f"  {nm:<22}{btc:>+11.1f}%{eq:>+17.1f}%")
print("  "+"─"*66)
b=F['BTC']['close'].values
print(f"  BTC 월평균(241일 기준): {((b[n0-1]/b[0])**(30/241)-1)*100:+.1f}%/월")
