import glob, json, os, sys, numpy as np, pandas as pd
PC='/Users/l/project/8888/lab_cache_tf'; FC='/Users/l/project/8888/lab_funding'
def load():
    out={}
    for p in sorted(glob.glob(f'{PC}/1h_*.json')):
        key=os.path.basename(p).split('1h_')[1].replace('.json','')
        fp=f'{FC}/{key}.json'
        if not os.path.exists(fp): continue
        df=pd.DataFrame(json.load(open(p)),columns=['ts','open','high','low','close','volume'])
        c,h,l=df['close'],df['high'],df['low']; pc=c.shift(1)
        tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
        df['atr']=tr.ewm(span=14,adjust=False).mean(); df['atr_pct']=df['atr']/c
        fd=pd.DataFrame(json.load(open(fp)),columns=['ts','fr']).drop_duplicates('ts').sort_values('ts')
        # 각 봉에 직전 펀딩률을 붙인다(미래참조 방지)
        df=pd.merge_asof(df.sort_values('ts'),fd,on='ts',direction='backward')
        df['fr']=df['fr'].astype(float)
        # 누적 펀딩(24h=3회) 및 z점수
        df['fr24']=df['fr'].rolling(24).mean()
        m=df['fr'].rolling(24*30).mean(); s=df['fr'].rolling(24*30).std()
        df['frz']=(df['fr']-m)/s
        if df['fr'].notna().sum()<len(df)*0.7: continue
        out[key.split('_USDT')[0]]=df.reset_index(drop=True)
    n=min(len(d) for d in out.values())
    return {k:v.iloc[-n:].reset_index(drop=True) for k,v in out.items()}
F=load(); n0=len(next(iter(F.values()))); mid=n0//2
print(f"  {len(F)}종목 · {n0}봉 = {n0/24:.0f}일 · 펀딩비 병합 완료")
btc=F['BTC'] if 'BTC' in F else next(iter(F.values()))
gate=np.where(btc['close'].values>btc['close'].ewm(span=480,adjust=False).mean().values,1,-1)
FEE=0.0007
def sim(df,sg,hold,k):
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
        if not done:
            last=c[min(j,end)]; o=(last-e)/e if lng else (e-last)/e
        res.append(o); busy=min(j,end)
    return res
def sig_contra(df,lo,hi,z=2.0,use_gate=True):
    """쏠림 역이용: 펀딩률 z가 극단이면 반대편으로."""
    frz=df['frz'].values; ap=df['atr_pct'].values; out=[]
    for i in range(max(lo,24*30+2),hi):
        if frz[i]!=frz[i] or ap[i]<=0: continue
        r=ap[i]*4.0
        if frz[i]>z and (not use_gate or gate[i]<0): out.append((i,'short',r))
        elif frz[i]<-z and (not use_gate or gate[i]>0): out.append((i,'long',r))
    return out
def sig_carry(df,lo,hi,z=1.5,use_gate=True):
    """캐리 순응: 펀딩이 음수(숏 과밀)면 롱, 양수 극단이면 숏 — 게이트 동조."""
    frz=df['frz'].values; ap=df['atr_pct'].values; fr=df['fr'].values; out=[]
    for i in range(max(lo,24*30+2),hi):
        if frz[i]!=frz[i] or ap[i]<=0: continue
        r=ap[i]*4.0
        if fr[i]<0 and frz[i]<-z and (not use_gate or gate[i]>0): out.append((i,'long',r))
        elif fr[i]>0 and frz[i]>z and (not use_gate or gate[i]<0): out.append((i,'short',r))
    return out
def sig_trend(df,lo,hi,z=1.0,use_gate=True):
    """추세 동조: 펀딩이 상승(롱 유입)하고 시장도 상승이면 롱."""
    frz=df['frz'].values; ap=df['atr_pct'].values; c=df['close'].values
    ema=pd.Series(c).ewm(span=120,adjust=False).mean().values; out=[]
    for i in range(max(lo,24*30+2),hi):
        if frz[i]!=frz[i] or ap[i]<=0: continue
        r=ap[i]*4.0
        up=c[i]>ema[i]
        if frz[i]>z and up and (not use_gate or gate[i]>0): out.append((i,'long',r))
        elif frz[i]<-z and not up and (not use_gate or gate[i]<0): out.append((i,'short',r))
    return out
def run(fn,lo,hi,nseg,**kw):
    tot=[];segs=[[] for _ in range(nseg)];step=(hi-lo)//nseg
    for s,df in F.items():
        sg=fn(df,lo,hi,**kw); tot+=sim(df,sg,72,4.0)
        for k in range(nseg):
            segs[k]+=sim(df,[x for x in sg if lo+k*step<=x[0]<lo+(k+1)*step],72,4.0)
    def sc(r): return (len(r), 100*sum(1 for x in r if x>0)/len(r) if r else 0, (sum(r)-FEE*len(r))*100)
    return sc(tot),[sc(s) for s in segs]
print("  "+"═"*76)
print(f"  {'가설':<30}{'건수':>6}{'승률':>7}{'개발순':>10}   3분할")
print("  "+"─"*76)
V=[('①쏠림역이용 z2.0+게이트',sig_contra,dict(z=2.0)),
   ('①쏠림역이용 z2.0 게이트無',sig_contra,dict(z=2.0,use_gate=False)),
   ('①쏠림역이용 z1.5+게이트',sig_contra,dict(z=1.5)),
   ('②캐리순응 z1.5+게이트',sig_carry,dict(z=1.5)),
   ('②캐리순응 z1.0+게이트',sig_carry,dict(z=1.0)),
   ('③추세동조 z1.0+게이트',sig_trend,dict(z=1.0)),
   ('③추세동조 z0.5+게이트',sig_trend,dict(z=0.5))]
ok=[]
for nm,fn,kw in V:
    o,ss=run(fn,mid,n0,3,**kw)
    mk=" ".join("+" if s[2]>0 else "-" for s in ss)
    g=o[0]>=40 and o[2]>0 and all(s[2]>0 for s in ss)
    print(f"  {nm:<30}{o[0]:>6}{o[1]:>6.0f}%{o[2]:>+9.1f}%   {mk} {'✅' if g else ''}")
    if g: ok.append((nm,fn,kw))
print("  "+"─"*76)
print(f"  개발 통과: {[x[0] for x in ok] or '없음'}")
if ok:
    print("\n  ■ 봉인 개봉 (앞 절반)")
    for nm,fn,kw in ok:
        o,_=run(fn,0,mid,1,**kw)
        print(f"  {nm:<30}{o[0]:>6}{o[1]:>6.0f}%{o[2]:>+9.1f}%   {'🟢통과' if o[2]>0 else '🔴탈락'}")
