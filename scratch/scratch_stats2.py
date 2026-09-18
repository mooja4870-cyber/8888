import pandas as pd
import json
import datetime
import os

bots = ['8401', '8402', '8410']

results = {}

for bot in bots:
    csv_path = f'/Users/l/project/{bot}/data/trade_history.csv'
    if not os.path.exists(csv_path):
        results[bot] = "File not found"
        continue
        
    try:
        # Some files might have BOM
        try:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
        except:
            df = pd.read_csv(csv_path, encoding='cp949')
            
        if df.empty:
            results[bot] = "Empty CSV"
            continue
            
        # We only care about rows where 유형 is 청산 (exit) to calculate realized PnL accurately
        df = df[df['유형'] == '청산'].copy()
        
        df['시간'] = pd.to_datetime(df['시간'])
        df = df.sort_values('시간')
        
        df['수익(USDT)'] = pd.to_numeric(df['수익(USDT)'], errors='coerce').fillna(0)
        
        # Calculate cumulative profit
        df['cumulative_pnl'] = df['수익(USDT)'].cumsum()
        
        peak_pnl = df['cumulative_pnl'].max()
        current_pnl = df['cumulative_pnl'].iloc[-1] if not df.empty else 0
        
        # Determine when peak happened
        peak_time = df.loc[df['cumulative_pnl'].idxmax()]['시간'] if peak_pnl > 0 and not df.empty else None
        peak_time_str = peak_time.strftime('%Y-%m-%d %H:%M:%S') if peak_time else "N/A"
        
        drop_amount = peak_pnl - current_pnl
        drop_percentage = (drop_amount / peak_pnl) * 100 if peak_pnl > 0 else 0
        
        results[bot] = {
            'peak_time': peak_time_str,
            'current_pnl': current_pnl,
            'peak_pnl': peak_pnl,
            'drop_amount': drop_amount,
            'drop_percentage': round(drop_percentage, 2)
        }
        
    except Exception as e:
        results[bot] = f"Error: {e}"

print(json.dumps(results, indent=2))
