import os,sys
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from signals import Momentum, Donchian, EmaCross
from sweep_tf import resample
from portfolio import simulate_portfolio, report

FOUR=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
raw={s:load(s) for s in FOUR}
CANDS=[("1d DON-20/H30","1D",Donchian(20),30),
       ("1d DON-20/H14","1D",Donchian(20),14),
       ("1d DON-40/H14","1D",Donchian(40),14),
       ("1d MOM-20/H3", "1D",Momentum(20),3),
       ("1d MOM-30/H3", "1D",Momentum(30),3),
       ("1d EMA-8/21/H3","1D",EmaCross(8,21),3),
       ("4h MOM-3/H42", "4h",Momentum(3),42)]
print("종목 4개 · 비관비용 · 2년 · 포지션 상한별")
print("%-16s %4s %6s %9s %8s  %-30s %s"%("전략","상한","건수","순손익","건당bp","4분할","흑자"))
for label,rule,sig,hold in CANDS:
    data={s:resample(raw[s],rule) for s in FOUR}
    for cap in (3,4):
        tr=simulate_portfolio(data,sig,hold,max_positions=cap)
        r=report(tr,data)
        if not r: continue
        print("%-16s %4d %6d %+9.2f %+8.1f  %-30s %d/%d %s"%(
            label,cap,r["n"],r["net"],r["edge_bp"],
            " ".join("%+6.2f"%p for p in r["parts"]),r["pos"],r["nsym"],
            "O" if r["all_pos"] else "X"))
