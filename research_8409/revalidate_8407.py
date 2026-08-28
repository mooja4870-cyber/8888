"""8407에 배포한 1h MOM-12/H24를 2년치로 재검증한다."""
import sys, os
sys.path.insert(0, "/Users/l/project/8888/research_8407")
os.environ["BT_DATA_DIR"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
import backtest_8407 as B
B.DATA_DIR = os.environ["BT_DATA_DIR"]
from backtest_8407 import load, simulate, Variant, FEE_MAKER, FEE_TAKER
from signals import Momentum
from sweep_tf import resample

SYMS = ["SOL/USDT:USDT","ETH/USDT:USDT","XRP/USDT:USDT","DOGE/USDT:USDT"]
data = {s: resample(load(s), "1h") for s in SYMS}
k0 = next(iter(data))
print(f"기간 {data[k0].timestamp.iloc[0]} ~ {data[k0].timestamp.iloc[-1]} ({len(data[k0])}봉 × {len(data)}종목)\n")

def run(sig, cfg, nsplit=4):
    t, bysym = [], {}
    for s, df in data.items():
        u = simulate(df, sig, cfg); bysym[s] = sum(x["net"] for x in u); t += u
    parts = []
    for k in range(nsplit):
        tot = 0.0
        for s, df in data.items():
            lo, hi = len(df)*k//nsplit, len(df)*(k+1)//nsplit
            tot += sum(x["net"] for x in simulate(df.iloc[lo:hi].reset_index(drop=True), sig, cfg))
        parts.append(tot)
    g = sum(x["gross"] for x in t)
    return len(t), g, sum(x["net"] for x in t), parts, bysym

print("배포 설정 = 1h · MOM-12 · H24")
print("%-22s %6s %9s %9s  %-30s %s"%("비용","건수","총이익","순손익","4분할(6개월씩)","흑자"))
for lbl, ef, xf, tf in (("비관 전부taker",FEE_TAKER,FEE_TAKER,None),
                        ("낙관 maker+TP",FEE_MAKER,FEE_TAKER,FEE_MAKER)):
    cfg = Variant("x", timeout_bars=0, entry_fee=ef, exit_fee=xf, tp_exit_fee=tf, max_hold_bars=24)
    n,g,net,parts,bysym = run(Momentum(12), cfg)
    pos = sum(1 for v in bysym.values() if v>0)
    print("%-22s %6d %+9.2f %+9.2f  %-30s %d/4"%(lbl,n,g,net," ".join("%+6.2f"%p for p in parts),pos))
print()
print("종목별(비관):", "  ".join(f"{s.split('/')[0]}:{v:+.2f}" for s,v in run(Momentum(12), Variant("x",timeout_bars=0,max_hold_bars=24))[4].items()))
