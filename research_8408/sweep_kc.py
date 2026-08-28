"""켈트너 채널 돌파 2년 스윕 + 기존 3봇과의 겹침 측정."""
import os,sys
HERE=os.path.dirname(os.path.abspath(__file__))
os.environ["BT_DATA_DIR"]="/Users/l/project/8888/research_8409/data"
for p in ("/Users/l/project/8888/research_8407","/Users/l/project/8888/research_8409",
          "/Users/l/project/8888/research_8410",HERE): sys.path.insert(0,p)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from sweep_tf import resample
from portfolio import simulate_portfolio
from bb_signal import KeltnerBreakout, BollingerBreakout
from signals import Donchian

FIVE=["SOL/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT","ADA/USDT:USDT","BNB/USDT:USDT"]
SEED=10.0
raw={s:load(s) for s in FIVE}
D1={s:resample(raw[s],"1D") for s in FIVE}
D4={s:resample(raw[s],"4h") for s in FIVE}

def ks(tr): return {(x["symbol"],x["t"].date()) for x in tr}
k07=ks(simulate_portfolio(D1,Donchian(30),7,max_positions=5,notional=5.7))
k09=ks(simulate_portfolio(D1,Donchian(20),30,max_positions=5,notional=5.7))
k10=ks(simulate_portfolio(D4,BollingerBreakout(40,2.5),42,max_positions=5,notional=5.7))

def run(data,sig,h):
    tr=sorted(simulate_portfolio(data,sig,h,max_positions=5,notional=5.7),key=lambda x:x["t"])
    if not tr: return None
    bal=mn=peak=SEED; dd=0
    for x in tr:
        bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); dd=max(dd,peak-bal)
    ts=[x["t"] for x in tr]
    parts=[sum(x["net"] for x in tr if ts[len(ts)*k//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(k+1)//4)]) for k in range(4)]
    bysym={}
    for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
    kk=ks(tr)
    return dict(n=len(tr),net=bal-SEED,mn=mn,dd=100*dd/peak,parts=parts,
                pos=sum(1 for v in bysym.values() if v>0),
                ov=(100*len(kk&k07)/len(kk),100*len(kk&k09)/len(kk),100*len(kk&k10)/len(kk)),
                ok=all(p>0 for p in parts) and sum(1 for v in bysym.values() if v>0)>=4 and len(tr)>=100)

print("켈트너 채널 돌파 · 5종목 · 상한5 · 비관비용 · 2년")
print("%-18s %5s %8s %7s %6s %-28s %5s %s"%("구성","건수","순손익","최저","낙폭","4분할","흑자","겹침 07/09/10"))
rows=[]
for tf,data,holds in (("1d",D1,(7,14,30)),("4h",D4,(12,42,90))):
    for p in (10,20,30,50):
        for k in (1.5,2.0,2.5):
            for h in holds:
                r=run(data,KeltnerBreakout(p,k),h)
                if r is None: continue
                r["label"]="%s KC-%d/%.1f H%d"%(tf,p,k,h)
                rows.append(r)
                if r["ok"]:
                    print("%-18s %5d %+8.2f %7.2f %5.0f%% %-28s %d/5 %2.0f/%2.0f/%2.0f%%"%(
                        r["label"],r["n"],r["net"],r["mn"],r["dd"],
                        " ".join("%+6.2f"%z for z in r["parts"]),r["pos"],*r["ov"]))
ok=[r for r in rows if r["ok"]]
print("\n통과 %d건 / 전체 %d"%(len(ok),len(rows)))
if not ok and rows:
    b=max(rows,key=lambda r:r["net"])
    print("최고:",b["label"],"%+.2f"%b["net"],["%+.2f"%p for p in b["parts"]],"흑자%d/5"%b["pos"])
