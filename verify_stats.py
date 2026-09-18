import pandas as pd
import os

bots = ["8401", "8402", "8410"]
for b in bots:
    csv_path = f"/Users/l/project/{b}/data/trade_history.csv"
    if not os.path.exists(csv_path):
        print(f"[{b}] File not found: {csv_path}")
        continue
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"[{b}] Error reading CSV: {e}")
        continue
    
    if "pnl_pct" not in df.columns:
        print(f"[{b}] pnl_pct column missing")
        continue

    # Filter out entries that might be 'entry' only if there's such a thing, or if pnl_pct is present and not NaN
    # Actually, let's see how wins and losses are determined.
    # Typically, PNL > 0 is win, PNL <= 0 is loss.
    # Let's count valid trades.
    trades = df.dropna(subset=['pnl_pct']).copy()
    
    wins = (trades['pnl_pct'] > 0).sum()
    losses = (trades['pnl_pct'] <= 0).sum()
    
    # sequence (last 30 trades, oldest to newest? or newest to oldest?)
    # Usually newest is at the bottom.
    recent_30 = trades['pnl_pct'].tail(30).tolist()
    seq_str = "".join(["O" if p > 0 else "x" for p in recent_30][::-1]) # newest first
    # group by 5
    seq_grouped = " ".join([seq_str[i:i+5] for i in range(0, len(seq_str), 5)])
    
    print(f"[{b}]")
    print(f"  Trades: {len(trades)}")
    print(f"  W/L: {wins}W/{losses}L")
    print(f"  Seq (newest first, grouped): {seq_grouped}")
    
