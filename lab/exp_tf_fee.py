"""B안 검증 — 타임프레임과 수수료를 바꾸면 판이 바뀌는가."""
import sys, glob, json; sys.path.insert(0,'/Users/l/project/8888')
import numpy as np, pandas as pd

MIN={'15m':15,'1h':60,'4h':240}

def load(tf):
    d = '/Users/l/project/8888/lab_cache_180' if tf=='15m' else '/Users/l/project/8888/lab_cache_tf'
    pat = f'{d}/binance_15m_*.json' if tf=='15m' else f'{d}/{tf}_*.json'
    out={}
    for p in sorted(glob.glob(pat)):
        df=pd.DataFrame(json.load(open(p)),columns=['ts','open','high','low','close','volume'])
        c,h,l=df['close'],df['high'],df['low']; pc=c.shift(1)
        tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
        df['atr']=tr.ewm(span=14,adjust=False).mean(); df['atr_pct']=df['atr']/c
        k=p.split('_')[-1].split('_USDT')[0].replace('.json','')
        out[k]=df
    n=min(len(x) for x in out.values())
    return {k:v.iloc[-n:].reset_index(drop=True) for k,v in out.items()}

def gate(frames, span=200):
    src = frames.get('BTC')
    if src is None: src=next(iter(frames.values()))
    c=src['close']; return np.where(c.values > c.ewm(span=span,adjust=False).mean().values, 1, -1)

def signals(df,g,lo,hi,p,sq,atr_sl):
    c,h,l=(df[k].values for k in ('close','high','low')); ap=df['atr_pct'].values
    apm=pd.Series(ap).rolling(p*3).mean().values
    hh=pd.Series(h).rolling(p).max().shift(1).values
    ll=pd.Series(l).rolling(p).min().shift(1).values
    out=[]
    for i in range(max(p*3+2,lo),hi):
        if not (apm[i]==apm[i]) or ap[i]<=0 or apm[i]<=0: continue
        if sq < 1.0 and ap[i]>apm[i]*sq: continue
        if g[i]>0 and c[i]>hh[i]: out.append((i,'long',ap[i]*atr_sl))
        elif g[i]<0 and c[i]<ll[i]: out.append((i,'short',ap[i]*atr_sl))
    return out

def sim(sigs,df,hold,kch,fee):
    h,l,c,atr=(df[k].values for k in ('high','low','close','atr')); n=len(df)
    res=[];busy=-1
    for i,d,risk in sigs:
        if i<=busy or risk<=0: continue
        e=c[i]; long=d=='long'; sl=e*(1-risk) if long else e*(1+risk); peak=e
        end=min(n-1,i+hold); j=i+1; done=False; o=0.0
        while j<=end:
            hi,lo=h[j],l[j]
            peak=max(peak,hi) if long else min(peak,lo)
            a=atr[j] if atr[j]==atr[j] else 0.0
            ch=peak-kch*a if long else peak+kch*a
            sl=max(sl,ch) if long else min(sl,ch)
            if (long and lo<=sl) or (not long and hi>=sl):
                o=(sl-e)/e if long else (e-sl)/e; done=True; break
            j+=1
        if not done:
            last=c[min(j,end)]; o=(last-e)/e if long else (e-last)/e
        res.append(o); busy=min(j,end)
    net=sum(res)-fee*len(res)
    return dict(n=len(res), wr=100*sum(1 for x in res if x>0)/len(res) if res else 0, net=net*100)

# 각 TF의 파라미터는 '시간'을 맞춘다: 레인지 24시간, 보유 72시간
SQ=1.0   # 수축 필터 해제 — 표본 확보 우선
PARAMS={'15m':dict(p=96,hold=288),'1h':dict(p=24,hold=72),'4h':dict(p=6,hold=18)}
print(f"  {'TF':<5}{'기간':<9}{'수수료':<8}{'건수':>6}{'승률':>7}{'개발순':>10}{'3분할':>9}{'봉인':>10}")
print("  "+"─"*66)
for tf in ('15m','1h','4h'):
    fr=load(tf); g=gate(fr); n0=len(next(iter(fr.values())))
    days=n0*MIN[tf]/60/24
    pr=PARAMS[tf]
    for fee in (0.0010, 0.0007, 0.0004):
        # 개발 = 뒤 절반, 봉인 = 앞 절반
        dev, seal = [], []
        segs=[[],[],[]]
        for sym,df in fr.items():
            n=len(df); mid=n//2
            sg=signals(df,g,mid,n,pr["p"],SQ,4.0)
            r=sim(sg,df,pr['hold'],4.0,fee); dev.append(r)
            step=(n-mid)//3
            for k in range(3):
                s2=[s for s in sg if mid+k*step<=s[0]<mid+(k+1)*step]
                segs[k].append(sim(s2,df,pr['hold'],4.0,fee))
            sg2=signals(df,g,0,mid,pr["p"],SQ,4.0)
            seal.append(sim(sg2,df,pr['hold'],4.0,fee))
        N=sum(x['n'] for x in dev); NET=sum(x['net'] for x in dev)
        W=sum(x['wr']*x['n'] for x in dev)/N if N else 0
        sm=" ".join("+" if sum(y['net'] for y in s)>0 else "-" for s in segs)
        SN=sum(x['net'] for x in seal)
        ok=NET>0 and all(sum(y['net'] for y in s)>0 for s in segs)
        print(f"  {tf:<5}{days:>4.0f}일   {fee*100:>4.2f}%  {N:>6}{W:>6.0f}%{NET:>+9.1f}%{sm:>9} {'✅' if ok else '  '}{SN:>+9.1f}%")
