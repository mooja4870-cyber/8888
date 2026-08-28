import os,sys,numpy as np
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from signals import Donchian
from sweep_tf import resample
from portfolio import simulate_portfolio

FOUR=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
SIX=FOUR+["BNB/USDT:USDT","ADA/USDT:USDT"]
raw={s:load(s) for s in SIX}
SEED=10.0

def stat(data,n,h,cap,notional,sl,tp):
    tr=simulate_portfolio(data,Donchian(n),h,max_positions=cap,notional=notional,sl_atr=sl,tp_atr=tp)
    if not tr: return None
    tr=sorted(tr,key=lambda x:x["t"])
    eq=np.cumsum([x["net"] for x in tr]); e=np.concatenate(([0.0],eq))
    dd=(np.maximum.accumulate(e)-e).max()
    ts=[x["t"] for x in tr]
    parts=[]
    for k in range(4):
        lo,hi=ts[len(ts)*k//4],ts[min(len(ts)-1,len(ts)*(k+1)//4)]
        parts.append(sum(x["net"] for x in tr if lo<=x["t"]<=hi))
    bysym={}
    for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
    return len(tr),eq[-1],dd,parts,sum(1 for v in bysym.values() if v>0),len(bysym)

print("계좌 $10 · 레버 3배 · 최소 명목가 $5 제약 하에서")
print("%-22s %5s %6s %8s %9s %-28s %s"%("구성","건수","수익%","최대낙폭%","순손익","4분할","흑자"))
for tag,syms in (("4종목",FOUR),("6종목",SIX)):
    data={s:resample(raw[s],"1D") for s in syms}
    for cap in (2,3,4):
        notional=min(SEED*3/cap, 7.0)      # 증거금 한도 내, 최소 $5 이상
        if notional<5.0: continue
        for sl,tp in ((2.0,4.0),(1.5,3.0),(1.0,2.0)):
            r=stat(data,20,30,cap,notional,sl,tp)
            if not r: continue
            n_,net,dd,parts,pos,nsym=r
            print("%-22s %5d %6.0f %8.0f %+9.2f %-28s %d/%d %s"%(
                "%s/상한%d/SL%.1f×"%(tag,cap,sl),n_,100*net/SEED,100*dd/SEED,net,
                " ".join("%+6.2f"%p for p in parts),pos,nsym,
                "O" if all(p>0 for p in parts) else "X"))
