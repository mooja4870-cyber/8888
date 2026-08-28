import os,sys
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407")
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from sweep_tf import resample
import numpy as np
SYMS=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
print("분기별 시장 국면 (일봉 기준)")
print("%-6s %-24s %10s %10s %10s"%("분기","기간","평균 보유수익","평균 |일변동|","추세성*"))
for k in range(4):
    rets,vols,trends=[],[],[]
    for s in SYMS:
        d=resample(load(s),"1D"); lo,hi=len(d)*k//4,len(d)*(k+1)//4
        c=d["close"].values[lo:hi]
        rets.append(100*(c[-1]/c[0]-1))
        lr=np.diff(np.log(c)); vols.append(100*np.abs(lr).mean())
        # 추세성 = |누적변화| / 경로길이 (1에 가까울수록 일방향, 0에 가까울수록 횡보)
        trends.append(abs(c[-1]-c[0])/np.abs(np.diff(c)).sum())
    d0=resample(load(SYMS[0]),"1D"); lo,hi=len(d0)*k//4,len(d0)*(k+1)//4
    per="%s~%s"%(d0['timestamp'].iloc[lo].date(),d0['timestamp'].iloc[hi-1].date())
    print("Q%d     %-24s %+9.1f%% %9.2f%% %10.3f"%(k+1,per,np.mean(rets),np.mean(vols),np.mean(trends)))
print("\n* 추세성: 순변화/경로길이. 낮을수록 횡보(추세추종에 불리)")
