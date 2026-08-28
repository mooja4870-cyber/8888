"""상위 후보를 '실제 매매 종목군'에서 검증한다. 10종목 결과를 4종목에 그대로 적용할 수 없다."""
import os, sys
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407")
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load, simulate, Variant, FEE_TAKER
from signals import Momentum, Donchian, EmaCross
from sweep_tf import resample

FOUR=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
TEN=FOUR+["BNB/USDT:USDT","ADA/USDT:USDT","AVAX/USDT:USDT","LINK/USDT:USDT","LTC/USDT:USDT","BTC/USDT:USDT"]
raw={s:load(s) for s in TEN}

CANDS=[("1d MOM-30/H3", "1D", Momentum(30), 3),
       ("1d MOM-20/H3", "1D", Momentum(20), 3),
       ("1d DON-20/H30","1D", Donchian(20), 30),
       ("1d DON-20/H14","1D", Donchian(20), 14),
       ("1d DON-40/H14","1D", Donchian(40), 14),
       ("1d EMA-8/21/H3","1D",EmaCross(8,21), 3),
       ("4h MOM-3/H42", "4h", Momentum(3), 42),
       ("4h MOM-9/H6",  "4h", Momentum(9), 6)]

def ev(sig, data, hold):
    cfg=Variant("x",timeout_bars=0,entry_fee=FEE_TAKER,exit_fee=FEE_TAKER,max_hold_bars=hold)
    t,bysym=[],{}
    for s,df in data.items():
        u=simulate(df,sig,cfg); bysym[s]=sum(x["net"] for x in u); t+=u
    parts=[]
    for k in range(4):
        tot=0.0
        for s,df in data.items():
            lo,hi=len(df)*k//4,len(df)*(k+1)//4
            tot+=sum(x["net"] for x in simulate(df.iloc[lo:hi].reset_index(drop=True),sig,cfg))
        parts.append(tot)
    return len(t),sum(x["net"] for x in t),parts,bysym

for label,rule,sig,hold in CANDS:
    print(f"\n{label}")
    for tag,syms in (("4종목(현행)",FOUR),("10종목",TEN)):
        data={s:resample(raw[s],rule) for s in syms}
        n,net,parts,bysym=ev(sig,data,hold)
        pos=sum(1 for v in bysym.values() if v>0)
        allpos=all(p>0 for p in parts)
        print(f"  {tag:12s} {n:5d}건 순 {net:+8.2f} | 4분할 {' '.join(f'{p:+6.2f}' for p in parts)} "
              f"| 흑자 {pos}/{len(syms)} | 전분기흑자 {'O' if allpos else 'X'}")
