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
raw={s:load(s) for s in SIX}
data={s:resample(raw[s],"1D") for s in SIX}

print("6종목 · 상한6 · 비관비용(전부 taker) · 2년 (2024-08-01~2026-08-27)")
print("%-14s %6s %9s %9s %9s  %-30s %s"%("전략","건수","총이익","수수료","순손익","4분할(6개월)","흑자"))
best=None
for n,h in ((15,30),(20,30),(25,30),(30,30),(40,30),(20,21),(15,21)):
    tr=simulate_portfolio(data,Donchian(n),h,max_positions=6)
    r=report(tr,data)
    fee=sum(x["fee"] for x in tr)
    print("DON-%-2d/H%-3d   %6d %+9.2f %9.2f %+9.2f  %-30s %d/%d %s"%(
        n,h,r["n"],r["gross"],-fee,r["net"],
        " ".join("%+6.2f"%p for p in r["parts"]),r["pos"],r["nsym"],
        "O" if r["all_pos"] else "X"))
    if n==20 and h==30: best=(tr,r)
tr,r=best
print("\n★ DON-20/H30 상세")
print("  종목별:", "  ".join(f"{s.split('/')[0]}:{v:+.2f}" for s,v in sorted(r["bysym"].items())))
print("  건당 총이익: %+.1f bp (왕복 비용 10bp)"%r["edge_bp"])
from collections import Counter
print("  청산유형:", dict(Counter(x["kind"] for x in tr)))
w=[x for x in tr if x["net"]>0]
print("  승률 %d/%d (%.0f%%)"%(len(w),len(tr),100*len(w)/len(tr)))
import numpy as np
print("  평균이익 %+.3f | 평균손실 %+.3f | 손익비 %.2f"%(
    np.mean([x["net"] for x in w]),
    np.mean([x["net"] for x in tr if x["net"]<=0]),
    abs(np.mean([x["net"] for x in w])/np.mean([x["net"] for x in tr if x["net"]<=0]))))
