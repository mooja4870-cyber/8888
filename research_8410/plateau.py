import os,sys
os.environ["BT_DATA_DIR"]="/Users/l/project/8888/research_8409/data"
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,"/Users/l/project/8888/research_8409"); sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from sweep_tf import resample
from portfolio import simulate_portfolio
from bb_signal import BollingerBreakout
FIVE=["SOL/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT","ADA/USDT:USDT","BNB/USDT:USDT"]
D4={s:resample(load(s),"4h") for s in FIVE}
print("4h 볼린저 이웃 지도 (순손익 / O=4분기 전부흑자 / 흑자종목)")
print("%-10s"%"" + "".join("%16s"%("H%d"%h) for h in (24,42,60)))
for p in (20,25,30,40,50):
    for k in (2.0,2.5,3.0):
        row="BB-%d/%.1f  "%(p,k)
        for h in (24,42,60):
            tr=simulate_portfolio(D4,BollingerBreakout(p,k),h,max_positions=5,notional=5.7)
            if not tr: row+="%16s"%"-"; continue
            ts=[x["t"] for x in sorted(tr,key=lambda z:z["t"])]
            trs=sorted(tr,key=lambda z:z["t"])
            parts=[sum(x["net"] for x in trs if ts[len(ts)*q//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(q+1)//4)]) for q in range(4)]
            bysym={}
            for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
            net=sum(x["net"] for x in tr)
            row+="%9.2f %s%d/5"%(net,"O" if all(z>0 for z in parts) else ".",sum(1 for v in bysym.values() if v>0))
        print(row)
