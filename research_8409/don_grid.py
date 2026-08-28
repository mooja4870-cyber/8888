"""돈치안 계열 고원 확인 + 종목/상한 조합. 기준은 사전 확정한 것 그대로."""
import os,sys
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from signals import Donchian
from sweep_tf import resample
from portfolio import simulate_portfolio, report

FOUR=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
SIX =FOUR+["BNB/USDT:USDT","ADA/USDT:USDT"]
EIGHT=SIX+["AVAX/USDT:USDT","LINK/USDT:USDT"]
raw={s:load(s) for s in EIGHT}

print("돈치안 1d 고원 지도 — O=4분기 전부흑자, 괄호=흑자종목수")
for tag,syms,cap in (("4종목/상한4",FOUR,4),("6종목/상한6",SIX,6),("8종목/상한8",EIGHT,8)):
    data={s:resample(raw[s],"1D") for s in syms}
    print("\n%s"%tag)
    print("%-8s"%"" + "".join("%18s"%("H%d"%h) for h in (7,14,21,30)))
    for n in (10,15,20,25,30,40):
        row="DON-%-4d"%n
        for h in (7,14,21,30):
            tr=simulate_portfolio(data,Donchian(n),h,max_positions=cap)
            r=report(tr,data)
            if not r: row+="%18s"%"-"; continue
            row+="%10.2f %s%d/%d"%(r["net"],"O" if r["all_pos"] else ".",r["pos"],r["nsym"])
        print(row)
