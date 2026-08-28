"""8409 개선 전후를 같은 조건에서 비교한다."""
import os,sys,numpy as np
HERE=os.path.dirname(os.path.abspath(__file__)); os.environ["BT_DATA_DIR"]=os.path.join(HERE,"data")
sys.path.insert(0,"/Users/l/project/8888/research_8407"); sys.path.insert(0,HERE)
import backtest_8407 as B; B.DATA_DIR=os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from signals import Momentum, Donchian
from sweep_tf import resample
from portfolio import simulate_portfolio

FOUR=["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
raw={s:load(s) for s in FOUR}
SEED=10.0

def run(rule,sig,hold,cap):
    data={s:resample(raw[s],rule) for s in FOUR}
    tr=sorted(simulate_portfolio(data,sig,hold,max_positions=cap,notional=7.0),key=lambda x:x["t"])
    bal=SEED; mn=SEED; peak=SEED; dd=0
    for x in tr:
        bal+=x["net"]; mn=min(mn,bal); peak=max(peak,bal); dd=max(dd,peak-bal)
    ts=[x["t"] for x in tr]
    parts=[sum(x["net"] for x in tr if ts[len(ts)*k//4]<=x["t"]<=ts[min(len(ts)-1,len(ts)*(k+1)//4)]) for k in range(4)]
    bysym={}
    for x in tr: bysym[x["symbol"]]=bysym.get(x["symbol"],0)+x["net"]
    w=[x for x in tr if x["net"]>0]; l=[x for x in tr if x["net"]<=0]
    g=sum(x["gross"] for x in tr); f=sum(x["fee"] for x in tr)
    return dict(n=len(tr),gross=g,fee=f,net=sum(x["net"] for x in tr),bal=bal,mn=mn,dd=100*dd/peak,
                parts=parts,pos=sum(1 for v in bysym.values() if v>0),bysym=bysym,
                wr=100*len(w)/len(tr),
                aw=np.mean([x["net"] for x in w]) if w else 0,
                al=np.mean([x["net"] for x in l]) if l else 0,
                edge=10000*g/(len(tr)*7.0))

before=run("1h",Momentum(30),48,3)   # 기존: 1h TSMOM 룩백30 / 보유48h / 상한3
after =run("1D",Donchian(20),30,4)   # 교체: 1d 돈치안20 / 보유30일 / 상한4

print("동일 조건 비교 — 2024-08-01~2026-08-27(2년) · SOL/ETH/XRP/DOGE · 비관비용(전부 taker) · 시드 $10")
print()
print("%-22s %18s %18s"%("항목","기존","교체"))
rows=[("진입 건수","%d건","n"),("총이익(수수료 전)","%+.2f USDT","gross"),
      ("총수수료","-%.2f USDT","fee"),("순손익","%+.2f USDT","net"),
      ("최종 잔고","$%.2f","bal"),("최저 잔고","$%.2f","mn"),
      ("최대낙폭(최고점 대비)","%.0f%%","dd"),("승률","%.0f%%","wr"),
      ("평균이익","%+.3f USDT","aw"),("평균손실","%+.3f USDT","al"),
      ("건당 총이익","%+.1f bp","edge"),("흑자 종목","%d/4","pos")]
for label,fmt,key in rows:
    print("%-22s %18s %18s"%(label,fmt%before[key],fmt%after[key]))
print("%-22s %18s %18s"%("손익비","%.2f : 1"%abs(before["aw"]/before["al"]),"%.2f : 1"%abs(after["aw"]/after["al"])))
print("%-22s %18s %18s"%("수익률(시드 대비)","%+.0f%%"%(100*(before["bal"]/SEED-1)),"%+.0f%%"%(100*(after["bal"]/SEED-1))))
print()
print("%-22s %18s %18s"%("4분기 손익","",""))
for i,q in enumerate(["Q1 24.08~25.02","Q2 25.02~25.08","Q3 25.08~26.02","Q4 26.02~26.08"]):
    print("  %-20s %18s %18s"%(q,"%+.2f"%before["parts"][i],"%+.2f"%after["parts"][i]))
print()
print("%-22s %18s %18s"%("종목별 손익","",""))
for s in FOUR:
    k=s.split("/")[0]
    print("  %-20s %18s %18s"%(k,"%+.2f"%before["bysym"].get(s,0),"%+.2f"%after["bysym"].get(s,0)))
