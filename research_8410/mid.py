import os,sys
os.environ["BT_DATA_DIR"]="/Users/l/project/8888/research_8409/data"
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,"/Users/l/project/8888/research_8409"); sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from sweep_tf import resample
from portfolio import simulate_portfolio
from bb_signal import BollingerBreakout
from signals import Donchian
FIVE=["SOL/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT","ADA/USDT:USDT","BNB/USDT:USDT"]
D4={s:resample(load(s),"4h") for s in FIVE}
D1={s:resample(load(s),"1D") for s in FIVE}
def ks(tr): return {(x["symbol"],x["t"].date()) for x in tr}
k07=ks(simulate_portfolio(D1,Donchian(30),7,max_positions=5,notional=5.7))
k09=ks(simulate_portfolio(D1,Donchian(20),30,max_positions=5,notional=5.7))
print("통과 영역 중앙 후보 (5종목·상한5·$5.70)")
print("%-16s %5s %9s %7s %6s %-28s %5s %s"%("구성","건수","순손익","최저","낙폭","4분할","흑자","겹침07/09"))
for p,k,h in ((30,2.5,42),(35,2.5,42),(40,2.5,42),(35,2.75,42),(35,2.5,48)):
    tr=sorted(simulate_portfolio(D4,BollingerBreakout(p,k),h,max_positions=5,notional=5.7),key=lambda x:x["t"])
    bal=mn=peak=10.0; dd=0
    for x in tr:
        bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); dd=max(dd,peak-bal)
    ts=[x["t"] for x in tr]
    parts=[sum(x["net"] for x in tr if ts[len(ts)*q//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(q+1)//4)]) for q in range(4)]
    bysym={}
    for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
    kk=ks(tr)
    print("BB-%d/%.2f H%-3d %5d %+9.2f %7.2f %5.0f%% %-28s %d/5 %s %2.0f%%/%2.0f%%"%(
        p,k,h,len(tr),bal-10.0,mn,100*dd/peak," ".join("%+6.2f"%z for z in parts),
        sum(1 for v in bysym.values() if v>0),"O" if all(z>0 for z in parts) else "X",
        100*len(kk&k07)/len(kk),100*len(kk&k09)/len(kk)))
