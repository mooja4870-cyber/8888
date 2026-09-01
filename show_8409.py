import os, sys, json
sys.path.insert(0, "/Users/l/project/8409")
from core.history_helper import load_local_trade_history, aggregate_and_pair_trades

raw_trades = load_local_trade_history()
paired = aggregate_and_pair_trades(raw_trades)
closed_trades = [p for p in paired if p.get("status") == "청산 완료"]
closed_trades.sort(key=lambda x: x.get("exit_time", ""))

N = len(closed_trades)
print(f"N={N}")
for i, t in enumerate(closed_trades):
    print(f"[{i+1}] {t.get('exit_time')} PNL={t.get('pnl_usdt')} {t.get('symbol')}")
