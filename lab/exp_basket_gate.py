import numpy as np, pandas as pd
exec(open('/tmp/fund_a.py').read().split("print(f\"  {len(F)}종목")[0])
F=load(); n0=len(next(iter(F.values()))); mid=n0//2; FEE=0.0007
# 바스켓 지수 = 15종목 정규화 평균
idx=np.mean([d['close'].values/d['close'].values[0] for d in F.values()],axis=0)
bg=np.where(idx>pd.Series(idx).ewm(span=480,adjust=False).mean().values,1,-1)
btc=F['BTC']['close'].values
btcg=np.where(btc>pd.Series(btc).ewm(span=480,adjust=False).mean().values,1,-1)
print(f"  게이트 일치율(BTC vs 바스켓): {(bg==btcg).mean()*100:.0f}%  ·  롱허용비율 BTC {(btcg>0).mean()*100:.0f}% / 바스켓 {(bg>0).mean()*100:.0f}%")
def sim(df,sg,hold=72,k=4.0):
    h,l,c,atr=(df[x].values for x in ('high','low','close','atr')); n=len(df); res=[];busy=-1
    for i,d,risk in sg:
        if i<=busy or risk<=0: continue
        e=c[i]; lng=d=='long'; sl=e*(1-risk) if lng else e*(1+risk); pk=e
        end=min(n-1,i+hold); j=i+1; done=False; o=0.0
        while j<=end:
            pk=max(pk,h[j]) if lng else min(pk,l[j])
            a=atr[j] if atr[j]==atr[j] else 0.0
            ch=pk-k*a if lng else pk+k*a
            sl=max(sl,ch) if lng else min(sl,ch)
            if (lng and l[j]<=sl) or (not lng and h[j]>=sl):
                o=(sl-e)/e if lng else (e-sl)/e; done=True; break
            j+=1
        if not done: last=c[min(j,end)]; o=(last-e)/e if lng else (e-last)/e
        res.append(o); busy=min(j,end)
    return res
def donch(df,g,lo,hi,p=24):
    c,h,l=(df[x].values for x in ('close','high','low')); ap=df['atr_pct'].values
    hh=pd.Series(h).rolling(p).max().shift(1).values; ll=pd.Series(l).rolling(p).min().shift(1).values
    out=[]
    for i in range(max(lo,p+2),hi):
        if ap[i]<=0 or hh[i]!=hh[i]: continue
        r=ap[i]*4.0
        if g[i]>0 and c[i]>hh[i]: out.append((i,'long',r))
        elif g[i]<0 and c[i]<ll[i]: out.append((i,'short',r))
    return out
def run(g,lo,hi,nseg):
    tot=[];segs=[[] for _ in range(nseg)];step=(hi-lo)//nseg
    for s,df in F.items():
        sg=donch(df,g,lo,hi); tot+=sim(df,sg)
        for k in range(nseg): segs[k]+=sim(df,[x for x in sg if lo+k*step<=x[0]<lo+(k+1)*step])
    sc=lambda r:(len(r),100*sum(1 for x in r if x>0)/len(r) if r else 0,(sum(r)-FEE*len(r))*100)
    return sc(tot),[sc(s) for s in segs]
print("  "+"═"*68)
print(f"  {'게이트':<20}{'건수':>6}{'승률':>7}{'개발순':>10}   3분할")
print("  "+"─"*68)
for nm,g in (('BTC 기준(기존)',btcg),('바스켓 기준(신)',bg)):
    o,ss=run(g,mid,n0,3); mk=" ".join("+" if s[2]>0 else "-" for s in ss)
    ok=o[2]>0 and all(s[2]>0 for s in ss)
    print(f"  {nm:<20}{o[0]:>6}{o[1]:>6.0f}%{o[2]:>+9.1f}%   {mk} {'✅' if ok else ''}")
    if ok:
        o2,_=run(g,0,mid,1)
        print(f"    └ 봉인: {o2[0]}건 {o2[1]:.0f}% {o2[2]:+.1f}%  {'🟢' if o2[2]>0 else '🔴'}")
