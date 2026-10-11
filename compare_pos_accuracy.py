import pandas as pd

df = pd.read_csv('/Users/l/project/8402/data/trade_history.csv')
df['시간'] = pd.to_datetime(df['시간'])
df['수익(USDT)'] = pd.to_numeric(df['수익(USDT)'])
df_exit = df[df['유형'].isin(['청산', '부분청산'])].copy()

split_date = pd.to_datetime("2026-09-11 13:48:55")

# group exits into positions by symbol (assuming 1 active position per symbol)
# we can just sum PNL per symbol per period for a rough proxy, but a symbol could be traded multiple times.
# Let's just calculate the RR.
def calc_rr(data):
    wins = data[data['수익(USDT)'] > 0]['수익(USDT)'].mean()
    losses = data[data['수익(USDT)'] <= 0]['수익(USDT)'].mean()
    if pd.isna(wins): wins = 0
    if pd.isna(losses) or losses == 0: return float('inf')
    return abs(wins / losses)

before = df_exit[df_exit['시간'] < split_date]
after = df_exit[df_exit['시간'] >= split_date]

print(f"Before RR: {calc_rr(before):.2f}")
print(f"After RR: {calc_rr(after):.2f}")
