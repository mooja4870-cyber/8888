"""실거래의 비대칭 보유규칙이 대칭 상한보다 나은가 — 손실은 일찍, 수익은 길게."""
import sys; sys.path.insert(0,"/Users/l/project/8888/lab")
import json, numpy as np, pandas as pd
from verify_tf_exit_scaling import load, SIG15, FEE, MAX_POS

frames=load("15m"); n0=len(next(iter(frames.values()))); mid=n0//2
sigs=json.load(open(SIG15))
ema=lambda a,s: pd.Series(a).ewm(span=s,adjust=False).mean().values
gates={s: np.where(d["close"].values>ema(d["close"].values,48),1,-1) for s,d in frames.items()}

def run(df,s,k,soft,hard):
    """soft봉에서 손실이면 청산, 수익이면 hard봉까지 유예 (TIMEOUT_SKIP_PROFITABLE 재현)."""
    h,l,c=df["high"].values,df["low"].values,df["close"].values; atr=df["_atr"].values; n=len(c)
    i,e,risk,rr=s["i"],s["e"],s["risk"],s["rr"]; long=s["dir"]=="long"
    tp=risk*rr; sl=e*(1-risk) if long else e*(1+risk); peak=e
    end=min(n-1,i+hard); j=i
    while j<=end:
        gain=(h[j]-e)/e if long else (e-l[j])/e
        if (long and l[j]<=sl) or (not long and h[j]>=sl):
            return j,((sl-e)/e if long else (e-sl)/e)-FEE
        if gain>=tp: return j,tp-FEE
        if j-i>=soft:                                  # 소프트 상한 도달
            cur=(c[j]-e)/e if long else (e-c[j])/e
            if cur<=0: return j,cur-FEE                # 손실이면 자른다
        peak=max(peak,h[j]) if long else min(peak,l[j])
        a=atr[j] if atr[j]==atr[j] else 0.0
        ch=(peak-k*a) if long else (peak+k*a)
        sl=max(sl,ch) if long else min(sl,ch); j+=1
    last=c[min(j,end)]
    return min(j,end),((last-e)/e if long else (e-last)/e)-FEE

def sim(lo,hi,k,soft,hard):
    allsig=sorted(((x["i"],s,x) for s,v in sigs.items() for x in v if lo<=x["i"]<hi),key=lambda t:t[0])
    busy,openp,pnl={},[],[]
    for i,sym,s in allsig:
        openp=[x for x in openp if x>i]
        if busy.get(sym,-1)>=i or len(openp)>=MAX_POS: continue
        if (gates[sym][i-1]>0)!=(s["dir"]=="long"): continue
        ei,p=run(frames[sym],s,k,soft,hard); pnl.append(p); busy[sym]=ei; openp.append(ei)
    return sum(pnl)*100, len(pnl), sum(1 for x in pnl if x>0)

print("  15분봉 · K=4.0 · 게이트 ON · 61종목 180일")
print(f"  {'규칙':<34}{'봉인':>12}{'개발':>12}{'합':>10}")
print("  "+"─"*70)
rows=[("대칭 24봉 (백테 현행)",24,24),("대칭 48봉",48,48),("대칭 96봉",96,96),
      ("비대칭 24→96봉 (실거래 8403)",24,96),("비대칭 48→96봉",48,96),
      ("비대칭 12→96봉",12,96),("비대칭 24→192봉",24,192)]
base=None
for nm,soft,hard in rows:
    a,na,wa=sim(0,mid,4.0,soft,hard); b,nb,wb=sim(mid,n0,4.0,soft,hard)
    if base is None: base=(a,b); mark="  기준"
    else:
        d1,d2=a-base[0],b-base[1]
        mark="  ← 양쪽 개선" if (d1>0 and d2>0) else f"  (Δ{d1:+.1f}/{d2:+.1f})"
    print(f"  {nm:<34}{a:>11.1f}%{b:>11.1f}%{a+b:>9.1f}%{mark}")
