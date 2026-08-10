import numpy as np, pandas as pd
exec(open('/tmp/fund_a.py').read().split("print(f\"  {len(F)}종목")[0])
F=load()
rows=[]
for s,df in F.items():
    c=df['close'].values; frz=df['frz'].values
    for hz in (8,24,72):
        fw=pd.Series(c).shift(-hz).values/c-1
        m=(frz==frz)&(fw==fw)
        rows.append(pd.DataFrame({'sym':s,'hz':hz,'frz':frz[m],'fw':fw[m]}))
D=pd.concat(rows)
print(f"  표본 {len(D)//3:,}봉 × 15종목")
print("  "+"═"*72)
print(f"  {'펀딩비 z구간':<18}" + "".join(f"{f'+{h}시간 수익':>16}" for h in (8,24,72)))
print("  "+"─"*72)
bins=[(-99,-2,'매우 음수 (<-2)'),(-2,-1,'음수 (-2~-1)'),(-1,1,'보통 (-1~+1)'),
      (1,2,'양수 (+1~+2)'),(2,99,'매우 양수 (>+2)')]
for lo,hi,nm in bins:
    cells=[]
    for h in (8,24,72):
        d=D[(D.hz==h)&(D.frz>=lo)&(D.frz<hi)]
        cells.append(f"{d.fw.mean()*100:+.3f}% ({len(d):,})" if len(d)>50 else "부족")
    print(f"  {nm:<18}" + "".join(f"{x:>16}" for x in cells))
print("  "+"─"*72)
for h in (8,24,72):
    d=D[D.hz==h]
    print(f"  +{h}시간 상관계수(펀딩z vs 미래수익): {np.corrcoef(d.frz,d.fw)[0,1]:+.4f}   전체평균 {d.fw.mean()*100:+.3f}%")
