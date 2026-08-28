import os,sys,numpy as np
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from signals import Donchian
from sweep_tf import resample
from portfolio import simulate_portfolio
sys.path.insert(0,"/Users/l/project/8407")
from core.strategy import StrategyEngine as LiveEngine
from core.config import CFG as LIVECFG

class LiveSig:
    name="LIVE-8407"
    def __init__(self): self.e=LiveEngine(LIVECFG)
    def at(self, df, i):
        w=df.iloc[max(0,i-90):i+1]
        if len(w)<65: return None
        s=self.e.generate_signal(w,"BT")
        if s is None or s.direction=="none" or s.atr<=0: return None
        class S: pass
        o=S(); o.direction=s.direction; o.atr=float(s.atr); return o

FOUR=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
data={s:resample(load(s),"1D") for s in FOUR}
SEED=10.0
print("LOOKBACK=%s  TF=%s  HOLD=%sh"%(LIVECFG.TSMOM_LOOKBACK,LIVECFG.TIMEFRAME,LIVECFG.MAX_HOLDING_HOURS))
for tag,sig in (("라이브 core/strategy.py",LiveSig()),("참조 Donchian(30)",Donchian(30))):
    tr=sorted(simulate_portfolio(data,sig,7,max_positions=4,notional=7.0),key=lambda x:x["t"])
    bal=SEED; mn=SEED; peak=SEED; dd=0
    for x in tr:
        bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); dd=max(dd,peak-bal)
    ts=[x["t"] for x in tr]
    parts=[sum(x["net"] for x in tr if ts[len(ts)*k//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(k+1)//4)]) for k in range(4)]
    bysym={}
    for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
    print("%-24s %4d건 최종$%.2f(%+.0f%%) 최저$%.2f 낙폭%.0f%% | 4분할 %s | 흑자%d/4 %s"%(
        tag,len(tr),bal,100*(bal/SEED-1),mn,100*dd/peak,
        " ".join("%+5.2f"%p for p in parts),sum(1 for v in bysym.values() if v>0),
        "O" if all(p>0 for p in parts) else "X"))
