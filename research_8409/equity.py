import os,sys,numpy as np
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from signals import Donchian
from sweep_tf import resample
from portfolio import simulate_portfolio

FOUR=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
raw={s:load(s) for s in FOUR}
data={s:resample(raw[s],"1D") for s in FOUR}
SEED=10.0; HALT=SEED*0.70   # MAX_DRAWDOWN_PCT=0.30 → 잔고 $7 미만이면 신규진입 차단

for n,h,cap,notional in ((20,30,4,7.0),(20,30,3,7.0),(20,30,4,5.0)):
    tr=sorted(simulate_portfolio(data,Donchian(n),h,max_positions=cap,notional=notional),key=lambda x:x["t"])
    bal=SEED; halted=False; halt_at=None; mn=SEED; peak=SEED; maxdd=0
    for x in tr:
        if bal<HALT and not halted:
            halted=True; halt_at=x["t"]
        if halted: continue          # 가드 발동 후에는 신규 진입이 막힌다
        bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); maxdd=max(maxdd,peak-bal)
    print("DON-%d/H%d 상한%d 명목$%.1f: 최종잔고 $%.2f (%+.0f%%) | 최저 $%.2f | 최대낙폭 $%.2f (%.0f%%) | 가드발동 %s"%(
        n,h,cap,notional,bal,100*(bal/SEED-1),mn,maxdd,100*maxdd/SEED,
        halt_at.date() if halt_at else "없음"))
