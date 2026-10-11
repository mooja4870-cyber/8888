import pandas as pd

df = pd.read_csv('/Users/l/project/8402/data/trade_history.csv')
# Keep only exits
df_exit = df[df['유형'].isin(['청산', '부분청산'])].copy()
df_exit['시간'] = pd.to_datetime(df_exit['시간'])
df_exit['수익률(%)'] = pd.to_numeric(df_exit['수익률(%)'])

split_date = pd.to_datetime("2026-09-11 13:48:55")

before = df_exit[df_exit['시간'] < split_date]
after = df_exit[df_exit['시간'] >= split_date]

def print_stats(name, data):
    trades = len(data)
    if trades == 0:
        print(f"--- {name} --- No trades")
        return
    wins = len(data[data['수익률(%)'] > 0])
    losses = trades - wins
    win_rate = (wins / trades) * 100
    total_return = data['수익률(%)'].sum()
    avg_win = data[data['수익률(%)'] > 0]['수익률(%)'].mean() if wins > 0 else 0
    avg_loss = data[data['수익률(%)'] <= 0]['수익률(%)'].mean() if losses > 0 else 0
    
    print(f"--- {name} ---")
    print(f"Trades: {trades} ({wins}W {losses}L)")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Total return sum: {total_return:.2f}%")
    print(f"Avg Win: {avg_win:.2f}%, Avg Loss: {avg_loss:.2f}%")
    print(f"Avg RR: {abs(avg_win / avg_loss) if avg_loss != 0 else 'N/A'}")

print_stats("Before Scaleout (Single TP)", before)
print_stats("After Scaleout (Partial TP)", after)
