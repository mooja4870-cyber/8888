"""역추세 계열 2년 스윕 — 사전 확정 기준 그대로."""
import os,sys
HERE=os.path.dirname(os.path.abspath(__file__))
os.environ["BT_DATA_DIR"]="/Users/l/project/8888/research_8409/data"
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,"/Users/l/project/8888/research_8409"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from sweep_tf import resample
from portfolio import simulate_portfolio
from mr_signals import candidates

FIVE=["SOL/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT","ADA/USDT:USDT","BNB/USDT:USDT"]
SEED=10.0; MIN_TRADES=100; MIN_POS=0.70
raw={s:load(s) for s in FIVE}

def stat(data,sig,hold):
    tr=sorted(simulate_portfolio(data,sig,hold,max_positions=5,notional=5.7),key=lambda x:x["t"])
    if not tr: return None
    bal=mn=peak=SEED; dd=0
    for x in tr:
        bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); dd=max(dd,peak-bal)
    ts=[x["t"] for x in tr]
    parts=[sum(x["net"] for x in tr if ts[len(ts)*k//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(k+1)//4)]) for k in range(4)]
    bysym={}
    for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
    pos=sum(1 for v in bysym.values() if v>0)
    w=[x for x in tr if x["net"]>0]
    return dict(n=len(tr),net=bal-SEED,mn=mn,dd=100*dd/peak,parts=parts,pos=pos,nsym=len(bysym),
                wr=100*len(w)/len(tr),trades=tr,
                ok=all(p>0 for p in parts) and pos/len(bysym)>=MIN_POS and len(tr)>=MIN_TRADES)

rows=[]
for tf,rule,holds in (("1d","1D",(7,14,30)),("4h","4h",(12,42,90))):
    data={s:resample(raw[s],rule) for s in FIVE}
    print("\n━━ %s ━━"%tf)
    for h in holds:
        for sig in candidates():
            r=stat(data,sig,h)
            if r is None: continue
            r["tf"],r["sig"],r["hold"]=tf,sig.name,h
            rows.append(r)
            if r["ok"]:
                print("  ◎ %-16s H%-3d %4d건 승률%3.0f%% 순 %+7.2f 최저 %5.2f 낙폭%3.0f%% | 4분할 %s | 흑자 %d/5"%(
                    sig.name,h,r["n"],r["wr"],r["net"],r["mn"],r["dd"]," ".join("%+6.2f"%p for p in r["parts"]),r["pos"]))
ok=[r for r in rows if r["ok"]]
print("\n통과: %d건 / 전체 %d"%(len(ok),len(rows)))
if ok:
    from collections import Counter
    fam=Counter((r["tf"],r["sig"].split("-")[1]) for r in ok)
    print("계열별:",{f"{k[0]}/{k[1]}":v for k,v in fam.items()})
else:
    best=max(rows,key=lambda r:r["net"]) if rows else None
    if best: print("최고 순손익:",best["sig"],"H%d"%best["hold"],"%+.2f"%best["net"],
                   "4분할",["%+.2f"%p for p in best["parts"]],"흑자 %d/5"%best["pos"])
