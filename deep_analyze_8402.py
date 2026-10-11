import pandas as pd

df = pd.read_csv('/Users/l/project/8402/data/trade_history.csv')
df['시간'] = pd.to_datetime(df['시간'])
df['수익(USDT)'] = pd.to_numeric(df['수익(USDT)'])
df_exit = df[df['유형'].isin(['청산', '부분청산'])].copy()

# Periods
p1_start = pd.to_datetime("2026-09-11 13:48:55")
p2_start = pd.to_datetime("2026-09-25 00:00:00")

period1 = df_exit[(df_exit['시간'] >= p1_start) & (df_exit['시간'] < p2_start)]
period2 = df_exit[df_exit['시간'] >= p2_start]

def print_stats(name, data):
    total_exits = len(data)
    if total_exits == 0:
        print(f"--- {name} --- No Exits")
        return
    total_pnl = data['수익(USDT)'].sum()
    wins = data[data['수익(USDT)'] > 0]
    losses = data[data['수익(USDT)'] <= 0]
    
    avg_win = wins['수익(USDT)'].mean() if len(wins) > 0 else 0
    avg_loss = losses['수익(USDT)'].mean() if len(losses) > 0 else 0
    
    rr = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
    
    print(f"--- {name} ---")
    print(f"Exits: {total_exits} ({len(wins)}W {len(losses)}L)")
    print(f"Total PNL: {total_pnl:.4f} USDT")
    print(f"Avg Win: {avg_win:.4f}, Avg Loss: {avg_loss:.4f}")
    print(f"Avg RR: {rr:.2f}")

print_stats("Phase 1: Sep 11 ~ Sep 24 (Uptrend)", period1)
print_stats("Phase 2: Sep 25 ~ Today (Downtrend)", period2)

# Print recent trades in Phase 2
print("\n--- Phase 2 Trade Breakdown ---")
print(period2[['시간', '심볼', '수익(USDT)', '청산유형']])
