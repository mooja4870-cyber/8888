import pandas as pd
import json
import datetime
import os

bots = ['8401', '8402', '8410']
now = datetime.datetime.now()
seven_days_ago = now - datetime.timedelta(days=7)

results = {}

for bot in bots:
    csv_path = f'/Users/l/project/{bot}/data/trade_history.csv'
    if not os.path.exists(csv_path):
        results[bot] = "File not found"
        continue
        
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            results[bot] = "Empty CSV"
            continue
            
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        df = df.sort_values('exit_time')
        
        # Calculate cumulative profit
        df['cumulative_pnl'] = df['pnl'].cumsum()
        
        # Filter for recent days to find peak
        recent_df = df[df['exit_time'] >= seven_days_ago]
        if recent_df.empty:
            recent_df = df # Fallback if no trades in 7 days
            
        peak_pnl = df['cumulative_pnl'].max()
        current_pnl = df['cumulative_pnl'].iloc[-1]
        
        # Peak within the last 7 days (or overall if needed)
        recent_peak = recent_df['cumulative_pnl'].max()
        
        results[bot] = {
            'current_cumulative_pnl': current_pnl,
            'recent_peak_pnl': recent_peak,
            'drop_amount': recent_peak - current_pnl,
            'drop_percentage': ((recent_peak - current_pnl) / max(recent_peak, 0.001)) * 100 if recent_peak > 0 else 0
        }
        
    except Exception as e:
        results[bot] = f"Error: {e}"

print(json.dumps(results, indent=2))
