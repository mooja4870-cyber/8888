import pandas as pd
import os

bots = ["8401", "8402", "8410"]
for b in bots:
    csv_path = f"/Users/l/project/{b}/data/trade_history.csv"
    if not os.path.exists(csv_path):
        print(f"[{b}] File not found: {csv_path}")
        continue
    
    # Read CSV skipping the BOM if necessary
    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
    except Exception as e:
        print(f"[{b}] Error reading CSV: {e}")
        continue
    
    col_type = "유형"
    col_pnl_pct = "수익률(%)"
    col_pnl_usdt = "수익(USDT)"
    col_mode = "매매모드"
    
    if col_type not in df.columns:
        print(f"[{b}] Column {col_type} missing, columns: {df.columns}")
        continue

    # Filter '청산' (exit) rows
    exits = df[df[col_type] == "청산"].copy()
    
    # Check if we should filter by date (SINCE time).
    # In 8888 app.py, the Discord bot reads perf_start_time.
    # Let's check stats.json for each bot to see perf_start_time.
    stats_path = f"/Users/l/project/{b}/data/stats.json"
    import json
    perf_start = None
    if os.path.exists(stats_path):
        with open(stats_path, 'r', encoding='utf-8') as f:
            st = json.load(f)
            perf_start = st.get("perf_start_time")
    
    if perf_start:
        exits = exits[exits["시간"] >= perf_start]
        
    exits[col_pnl_pct] = pd.to_numeric(exits[col_pnl_pct], errors='coerce').fillna(0)
    
    wins = (exits[col_pnl_pct] > 0).sum()
    losses = (exits[col_pnl_pct] <= 0).sum()
    
    recent_30 = exits[col_pnl_pct].tail(30).tolist()
    seq_str = "".join(["O" if p > 0 else "x" for p in recent_30][::-1])
    seq_grouped = " ".join([seq_str[i:i+5] for i in range(0, len(seq_str), 5)])
    
    # also calculate sun20 and yeok20 (from last 20 trades)
    recent_20_modes = exits.tail(20)
    sun20 = len(recent_20_modes[(recent_20_modes[col_pnl_pct] > 0) & (recent_20_modes[col_mode] == "순방향")])
    yeok20 = len(recent_20_modes[(recent_20_modes[col_pnl_pct] > 0) & (recent_20_modes[col_mode] == "역방향")])
    
    print(f"[{b}]")
    if perf_start:
        print(f"  Perf Start Time: {perf_start}")
    print(f"  Total Exits (Since Start): {len(exits)}")
    print(f"  W/L: {wins}W/{losses}L")
    print(f"  Seq: {seq_grouped}")
    print(f"  순20+역20 WINS: 순{sun20}+역{yeok20}")
    
