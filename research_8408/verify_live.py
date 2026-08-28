"""라이브 8408 코드를 그대로 import해 검증 결과를 재현하는지 확인한다."""
import os,sys
os.environ["BT_DATA_DIR"]="/Users/l/project/8888/research_8409/data"
for p in ("/Users/l/project/8888/research_8407","/Users/l/project/8888/research_8409",
          "/Users/l/project/8888/research_8410"): sys.path.insert(0,p)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from sweep_tf import resample
from portfolio import simulate_portfolio
from bb_signal import KeltnerBreakout
sys.path.insert(0,"/Users/l/project/8408")
from core.strategy import StrategyEngine
from core.config import CFG

class LiveKC:
    name="LIVE-8408"
    def __init__(self):
        self.e = StrategyEngine(CFG) if StrategyEngine.__init__.__code__.co_argcount>1 else StrategyEngine()
    def at(self, df, i):
        w=df.iloc[max(0,i-120):i+1]
        if len(w)<40: return None
        s=self.e.generate_signal(w,"BT")
        if s is None or s.direction=="none" or s.atr<=0: return None
        class S: pass
        o=S(); o.direction=s.direction; o.atr=float(s.atr)
        o.sl_price=float(s.swing_sl_price); o.tp_price=float(s.tp1_price); o.ref_price=float(s.close)
        return o

FIVE=["SOL/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT","ADA/USDT:USDT","BNB/USDT:USDT"]
D1={s:resample(load(s),"1D") for s in FIVE}
SEED=10.0
print("KC_PERIOD=%s KC_MULT=%s SL=%s TP=%s TF=%s"%(
    getattr(CFG,'KC_PERIOD','?'),getattr(CFG,'KC_MULT','?'),
    getattr(CFG,'KC_SL_ATR_MULT','?'),getattr(CFG,'KC_TP_ATR_MULT','?'),CFG.TIMEFRAME))
for tag,sig in (("라이브 core/strategy.py",LiveKC()),("참조 KC-20/1.5",KeltnerBreakout(20,1.5))):
    tr=sorted(simulate_portfolio(D1,sig,14,max_positions=5,notional=5.7),key=lambda x:x["t"])
    bal=mn=peak=SEED; dd=0
    for x in tr:
        bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); dd=max(dd,peak-bal)
    ts=[x["t"] for x in tr]
    parts=[sum(x["net"] for x in tr if ts[len(ts)*k//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(k+1)//4)]) for k in range(4)]
    bysym={}
    for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
    print("%-24s %4d건 최종$%.2f(%+.0f%%) 최저$%.2f 낙폭%.0f%% | 4분할 %s | 흑자%d/5 %s"%(
        tag,len(tr),bal,100*(bal/SEED-1),mn,100*dd/peak," ".join("%+5.2f"%z for z in parts),
        sum(1 for v in bysym.values() if v>0),"O" if all(z>0 for z in parts) else "X"))
