import os,sys,numpy as np
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from signals import Donchian
from sweep_tf import resample
from portfolio import simulate_portfolio, report

FOUR=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
SIX=FOUR+["BNB/USDT:USDT","ADA/USDT:USDT"]
raw={s:load(s) for s in SIX}

# 계좌 $10, 3배, 동시 6건 → 건당 명목가 = 10*3/6 = $5 (바이낸스 최소치와 동일)
# 백테스트는 $7을 썼으므로 5/7로 환산한다.
SCALE=5.0/7.0
for tag,syms,cap,notional in (("6종목/상한6",SIX,6,5.0),("4종목/상한4",FOUR,4,7.5)):
    data={s:resample(raw[s],"1D") for s in syms}
    for n,h in ((15,30),(20,30)):
        tr=simulate_portfolio(data,Donchian(n),h,max_positions=cap,notional=notional)
        tr=sorted(tr,key=lambda x:x["t"])
        eq=np.cumsum([x["net"] for x in tr])
        peak=np.maximum.accumulate(np.concatenate(([0.0],eq)))
        dd=peak-np.concatenate(([0.0],eq))
        seed=10.0
        print("%-12s DON-%-2d/H%-3d 건당명목 $%.1f | 순손익 %+7.2f (시드 $%.0f 대비 %+.0f%%) | 최대낙폭 %.2f USDT (%.0f%%)"%(
            tag,n,h,notional,eq[-1],seed,100*eq[-1]/seed,dd.max(),100*dd.max()/seed))
