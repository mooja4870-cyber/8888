import os,sys
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load, simulate, Variant, FEE_TAKER
from signals import Momentum, Donchian
from sweep_tf import resample
import numpy as np

SYMS=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]

# 종목별 시뮬로 방향 정보를 얻기 위해 simulate를 감싼다
def run(sig,rule,hold):
    out=[]
    for s in SYMS:
        df=resample(load(s),rule)
        cfg=Variant("x",timeout_bars=0,entry_fee=FEE_TAKER,exit_fee=FEE_TAKER,max_hold_bars=hold)
        # simulate는 방향을 남기지 않으므로 직접 재현
        a={k:df[k].values.astype(float) for k in ("open","high","low","close")}
        pos=None
        n=len(df)
        for i in range(60,n-1):
            if pos is not None:
                held=i-pos["i"]; hi,lo,cl=a["high"][i],a["low"][i],a["close"][i]
                px=kind=None
                if pos["dir"]=="long":
                    if lo<=pos["sl"]: px,kind=pos["sl"],"SL"
                    elif hi>=pos["tp"]: px,kind=pos["tp"],"TP"
                else:
                    if hi>=pos["sl"]: px,kind=pos["sl"],"SL"
                    elif lo<=pos["tp"]: px,kind=pos["tp"],"TP"
                if px is None and held>=hold: px,kind=cl,"MAXHOLD"
                if px is not None:
                    r=(px/pos["px"]-1)*(1 if pos["dir"]=="long" else -1)
                    out.append({"q":pos["q"],"dir":pos["dir"],"net":7.0*r-7.0*0.001})
                    pos=None
                continue
            sg=sig.at(df,i)
            if sg is None or sg.direction=="none" or sg.atr<=0: continue
            e=a["open"][i+1]
            sl,tp=(e-sg.atr*2,e+sg.atr*4) if sg.direction=="long" else (e+sg.atr*2,e-sg.atr*4)
            pos={"i":i,"px":e,"dir":sg.direction,"sl":sl,"tp":tp,"q":min(3,i*4//n)}
    return out

for label,rule,sig,hold in [("1d DON-20/H30","1D",Donchian(20),30),
                            ("1d MOM-20/H3","1D",Momentum(20),3)]:
    t=run(sig,rule,hold)
    print("\n%s — 분기 × 방향 순손익"%label)
    print("%-6s %10s %10s %10s %10s"%("","롱 건수","롱 손익","숏 건수","숏 손익"))
    for q in range(4):
        L=[x for x in t if x["q"]==q and x["dir"]=="long"]
        S=[x for x in t if x["q"]==q and x["dir"]=="short"]
        print("Q%d     %10d %+10.2f %10d %+10.2f"%(q+1,len(L),sum(x["net"] for x in L),len(S),sum(x["net"] for x in S)))
    L=[x for x in t if x["dir"]=="long"]; S=[x for x in t if x["dir"]=="short"]
    print("합계   %10d %+10.2f %10d %+10.2f"%(len(L),sum(x["net"] for x in L),len(S),sum(x["net"] for x in S)))
