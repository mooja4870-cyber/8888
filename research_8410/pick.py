"""상위 후보를 8407·8409와의 겹침까지 보고 고른다. 종목군은 실제 운용과 동일한 5종목."""
import os,sys
os.environ["BT_DATA_DIR"]="/Users/l/project/8888/research_8409/data"
sys.path.insert(0,"/Users/l/project/8888/research_8407")
sys.path.insert(0,"/Users/l/project/8888/research_8409")
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from sweep_tf import resample
from portfolio import simulate_portfolio
from signals import Donchian
from bb_signal import BollingerBreakout, KeltnerBreakout

FIVE=["SOL/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT","ADA/USDT:USDT","BNB/USDT:USDT"]
raw={s:load(s) for s in FIVE}
D1={s:resample(raw[s],"1D") for s in FIVE}
D4={s:resample(raw[s],"4h") for s in FIVE}
SEED=10.0; NOTIONAL=5.7; CAP=5

def keyset(tr): return {(x["symbol"],x["t"].date()) for x in tr}
def run(data,sig,hold):
    return sorted(simulate_portfolio(data,sig,hold,max_positions=CAP,notional=NOTIONAL),key=lambda x:x["t"])

t07=run(D1,Donchian(30),7); t09=run(D1,Donchian(20),30)
k07,k09=keyset(t07),keyset(t09)

CANDS=[("4h BB-30/2.5 H42",D4,BollingerBreakout(30,2.5),42),
       ("4h BB-50/2.5 H42",D4,BollingerBreakout(50,2.5),42),
       ("4h BB-10/1.5 H12",D4,BollingerBreakout(10,1.5),12),
       ("1d KC-20/1.5 H30",D1,KeltnerBreakout(20,1.5),30),
       ("1d BB-20/2   H14",D1,BollingerBreakout(20,2.0),14),
       ("1d BB-20/1.5 H30",D1,BollingerBreakout(20,1.5),30),
       ("1d BB-10/1.5 H30",D1,BollingerBreakout(10,1.5),30)]

print("5종목 · 상한5 · 명목가 $5.70 · 비관비용 · 2년")
print("%-18s %5s %8s %7s %6s %-28s %5s  %s"%("후보","건수","순손익","최저","낙폭","4분할","흑자","겹침 07/09"))
for label,data,sig,hold in CANDS:
    tr=run(data,sig,hold)
    if not tr: print("%-18s 진입 0건"%label); continue
    bal=mn=peak=SEED; dd=0
    for x in tr:
        bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); dd=max(dd,peak-bal)
    ts=[x["t"] for x in tr]
    parts=[sum(x["net"] for x in tr if ts[len(ts)*k//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(k+1)//4)]) for k in range(4)]
    bysym={}
    for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
    kk=keyset(tr)
    o7=100*len(kk&k07)/len(kk); o9=100*len(kk&k09)/len(kk)
    print("%-18s %5d %+8.2f %7.2f %5.0f%% %-28s %d/5 %s  %2.0f%%/%2.0f%%"%(
        label,len(tr),bal-SEED,mn,100*dd/peak," ".join("%+6.2f"%p for p in parts),
        sum(1 for v in bysym.values() if v>0),
        "O" if all(p>0 for p in parts) else "X",o7,o9))
