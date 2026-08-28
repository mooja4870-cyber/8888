import os,sys,numpy as np
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from signals import Donchian
from sweep_tf import resample
from portfolio import simulate_portfolio
FOUR=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
data={s:resample(load(s),"1D") for s in FOUR}
SEED=10.0
res={}
for tag,n,h in (("8409: DON-20/H30",20,30),("8407: DON-30/H7",30,7)):
    tr=sorted(simulate_portfolio(data,Donchian(n),h,max_positions=4,notional=7.0),key=lambda x:x["t"])
    bal=SEED; mn=SEED; peak=SEED; dd=0
    for x in tr:
        bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); dd=max(dd,peak-bal)
    ts=[x["t"] for x in tr]
    parts=[sum(x["net"] for x in tr if ts[len(ts)*k//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(k+1)//4)]) for k in range(4)]
    bysym={}
    for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
    w=[x for x in tr if x["net"]>0]
    res[tag]=tr
    print("%s | %d건 최종$%.2f(%+.0f%%) 최저$%.2f 낙폭%.0f%% 승률%.0f%% | 4분할 %s | 흑자%d/4 %s"%(
        tag,len(tr),bal,100*(bal/SEED-1),mn,100*dd/peak,100*len(w)/len(tr),
        " ".join("%+5.2f"%p for p in parts),sum(1 for v in bysym.values() if v>0),
        "O" if all(p>0 for p in parts) else "X"))
# 두 전략의 상관 — 같은 날 같은 방향으로 겹치는 정도
a,b=res["8409: DON-20/H30"],res["8407: DON-30/H7"]
da={(x["symbol"],x["t"].date()) for x in a}; db={(x["symbol"],x["t"].date()) for x in b}
print("\n청산 시점·종목 겹침: %d / %d (%.0f%%) — 낮을수록 분산"%(len(da&db),len(da),100*len(da&db)/len(da)))
