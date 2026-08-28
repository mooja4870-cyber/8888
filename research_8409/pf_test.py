"""MAX_POSITIONS=3을 반영해 후보를 재평가한다."""
import os,sys
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from signals import Momentum, Donchian, EmaCross
from sweep_tf import resample
from portfolio import simulate_portfolio, report

FOUR=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
SIX =FOUR+["BNB/USDT:USDT","ADA/USDT:USDT"]
raw={s:load(s) for s in set(SIX)}

CANDS=[("4h MOM-3 /H42","4h",Momentum(3),42),
       ("4h MOM-9 /H6", "4h",Momentum(9),6),
       ("1d MOM-20/H3", "1D",Momentum(20),3),
       ("1d MOM-30/H3", "1D",Momentum(30),3),
       ("1d DON-20/H30","1D",Donchian(20),30),
       ("1d DON-20/H14","1D",Donchian(20),14),
       ("1d EMA-8/21/H3","1D",EmaCross(8,21),3)]

print("MAX_POSITIONS=3 반영 · 비관비용(전부 taker) · 2년")
print("%-16s %-10s %6s %9s %8s  %-30s %s"%("전략","종목","건수","순손익","건당bp","4분할","흑자"))
for label,rule,sig,hold in CANDS:
    for tag,syms in (("4종목",FOUR),("6종목",SIX)):
        data={s:resample(raw[s],rule) for s in syms}
        tr=simulate_portfolio(data,sig,hold,max_positions=3)
        r=report(tr,data)
        if not r: print("%-16s %-10s  진입 0건"%(label,tag)); continue
        print("%-16s %-10s %6d %+9.2f %+8.1f  %-30s %d/%d %s"%(
            label,tag,r["n"],r["net"],r["edge_bp"],
            " ".join("%+6.2f"%p for p in r["parts"]),r["pos"],r["nsym"],
            "O" if r["all_pos"] else "X"))
