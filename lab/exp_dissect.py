import sys, glob, json, statistics; sys.path.insert(0,'/Users/l/project/8888')
import numpy as np, pandas as pd
exec(open('/tmp/grid_b.py').read().split('# 각 TF의 파라미터')[0])
fr=load('1h'); g=gate(fr); n0=len(next(iter(fr.values())))
mid=n0//2
def collect(lo,hi):
    rows=[]
    for sym,df in fr.items():
        sg=signals(df,g,lo,hi,24,1.0,4.0)
        h,l,c,atr=(df[k].values for k in ('high','low','close','atr')); n=len(df)
        busy=-1
        for i,d,risk in sg:
            if i<=busy or risk<=0: continue
            e=c[i]; long=d=='long'; sl=e*(1-risk) if long else e*(1+risk); peak=e
            end=min(n-1,i+72); j=i+1; done=False; o=0.0
            while j<=end:
                hi_,lo_=h[j],l[j]
                peak=max(peak,hi_) if long else min(peak,lo_)
                a=atr[j] if atr[j]==atr[j] else 0.0
                ch=peak-4.0*a if long else peak+4.0*a
                sl=max(sl,ch) if long else min(sl,ch)
                if (long and lo_<=sl) or (not long and hi_>=sl):
                    o=(sl-e)/e if long else (e-sl)/e; done=True; break
                j+=1
            if not done:
                last=c[min(j,end)]; o=(last-e)/e if long else (e-last)/e
            rows.append((sym,d,o)); busy=min(j,end)
    return rows
for nm,lo,hi in (('개발(뒤 180일)',mid,n0),('봉인(앞 180일)',0,mid)):
    rows=collect(lo,hi)
    pnl=[r[2] for r in rows]
    net=sum(pnl)-0.001*len(pnl)
    top=sorted(rows,key=lambda r:-r[2])[:5]
    print(f"  ══ {nm} ══  {len(rows)}건 · 순 {net*100:+.1f}%")
    print(f"    승 {sum(1 for x in pnl if x>0)} · 평균승 {statistics.mean([x for x in pnl if x>0])*100:+.2f}% · 평균패 {statistics.mean([x for x in pnl if x<=0])*100:+.2f}%")
    print(f"    상위5건 합계 {sum(t[2] for t in top)*100:+.1f}%  (전체의 {sum(t[2] for t in top)/sum(pnl)*100:.0f}%)")
    print("    최대: " + ", ".join(f"{t[0]} {t[1][:1]} {t[2]*100:+.0f}%" for t in top))
    from collections import Counter
    print("    롱/숏:", dict(Counter(r[1] for r in rows)))
    print()
