"""ETH(최소 명목가 $20, 진입 불가)를 뺀 종목군에서 두 봇 구성을 재검증한다."""
import os,sys
os.environ["BT_DATA_DIR"]=os.path.join(os.path.dirname(os.path.abspath(__file__)),"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from signals import Donchian
from sweep_tf import resample
from portfolio import simulate_portfolio
SEED=10.0
SETS={
 "현행 SOL/ETH/XRP/DOGE":["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"],
 "ETH→ADA":            ["SOL/USDT:USDT","ADA/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"],
 "ETH→BNB":            ["SOL/USDT:USDT","BNB/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"],
 "ETH 제외 3종목":       ["SOL/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"],
 "ADA+BNB 5종목":       ["SOL/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT","ADA/USDT:USDT","BNB/USDT:USDT"],
}
allsym=sorted({s for v in SETS.values() for s in v})
raw={s:load(s) for s in allsym}
for label,(n,h) in (("8407 DON-30/H7",(30,7)),("8409 DON-20/H30",(20,30))):
    print("\n%s"%label)
    print("  %-24s %5s %8s %8s %7s %-28s %s"%("종목군","건수","순손익","최저","낙폭","4분할","흑자"))
    for tag,syms in SETS.items():
        data={s:resample(raw[s],"1D") for s in syms}
        cap=len(syms)
        tr=sorted(simulate_portfolio(data,Donchian(n),h,max_positions=cap,notional=7.0),key=lambda x:x["t"])
        if not tr: continue
        bal=mn=peak=SEED; dd=0
        for x in tr:
            bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); dd=max(dd,peak-bal)
        ts=[x["t"] for x in tr]
        parts=[sum(x["net"] for x in tr if ts[len(ts)*k//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(k+1)//4)]) for k in range(4)]
        bysym={}
        for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
        pos=sum(1 for v in bysym.values() if v>0)
        print("  %-24s %5d %+8.2f %8.2f %6.0f%% %-28s %d/%d %s"%(
            tag,len(tr),bal-SEED,mn,100*dd/peak," ".join("%+6.2f"%p for p in parts),pos,len(syms),
            "O" if all(p>0 for p in parts) else "X"))
