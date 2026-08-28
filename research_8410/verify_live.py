"""라이브 8410 코드를 그대로 import해 검증 결과를 재현하는지 확인한다."""
import os,sys
os.environ["BT_DATA_DIR"]="/Users/l/project/8888/research_8409/data"
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,"/Users/l/project/8888/research_8409"); sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from sweep_tf import resample
from portfolio import simulate_portfolio
from bb_signal import BollingerBreakout
sys.path.insert(0,"/Users/l/project/8410")
from core.strategy import StrategyEngine as LiveEngine
from core.config import CFG as LC

class LiveSig:
    name="LIVE-8410"
    def __init__(self): self.e=LiveEngine(LC)
    def at(self, df, i):
        w=df.iloc[max(0,i-90):i+1]
        if len(w)<50: return None
        s=self.e.generate_signal(w,"BT")
        if s is None or s.direction=="none" or s.atr<=0: return None
        class S: pass
        o=S(); o.direction=s.direction; o.atr=float(s.atr); return o

FIVE=["SOL/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT","ADA/USDT:USDT","BNB/USDT:USDT"]
D4={s:resample(load(s),"4h") for s in FIVE}
print("BB_PERIOD=%s BB_STD_DEV=%s SL=%s TP=%s TF=%s"%(LC.BB_PERIOD,LC.BB_STD_DEV,
      getattr(LC,'BBTS_SL_ATR_MULT',None),getattr(LC,'BBTS_TP_ATR_MULT',None),LC.TIMEFRAME))
for tag,sig in (("라이브 core/strategy.py",LiveSig()),("참조 BB-40/2.5",BollingerBreakout(40,2.5))):
    tr=sorted(simulate_portfolio(D4,sig,42,max_positions=5,notional=5.7),key=lambda x:x["t"])
    bal=mn=peak=10.0; dd=0
    for x in tr:
        bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); dd=max(dd,peak-bal)
    ts=[x["t"] for x in tr]
    parts=[sum(x["net"] for x in tr if ts[len(ts)*q//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(q+1)//4)]) for q in range(4)]
    bysym={}
    for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
    print("%-24s %4d건 최종$%.2f(%+.0f%%) 최저$%.2f 낙폭%.0f%% | 4분할 %s | 흑자%d/5 %s"%(
        tag,len(tr),bal,100*(bal/10-1),mn,100*dd/peak," ".join("%+5.2f"%z for z in parts),
        sum(1 for v in bysym.values() if v>0),"O" if all(z>0 for z in parts) else "X"))
