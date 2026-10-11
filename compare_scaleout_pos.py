import pandas as pd

df = pd.read_csv('/Users/l/project/8402/data/trade_history.csv')
df['시간'] = pd.to_datetime(df['시간'])
df['수익(USDT)'] = pd.to_numeric(df['수익(USDT)'])
df_exit = df[df['유형'].isin(['청산', '부분청산'])].copy()

# Group by symbol and a time window or entry ID. Since trade_history.csv doesn't have an explicit position ID,
# we can assume consecutive exits for the same symbol within a few days belong to the same position,
# but it's easier to just aggregate by '심볼' and cumulative PnL, or we can look at the raw stats.json.

# Let's approximate position count:
# A new position is entered when '진입' happens.
entries = df[df['유형'] == '진입'].copy()
print(f"Total Entries: {len(entries)}")

# Let's just group exits by symbol and day? Or just print the total PNL sum.
# The Total return sum in % is a bit skewed by partials.
# Let's use '수익(USDT)' instead of '수익률(%)' to see absolute dollars.

split_date = pd.to_datetime("2026-09-11 13:48:55")

before = df_exit[df_exit['시간'] < split_date]
after = df_exit[df_exit['시간'] >= split_date]

print(f"--- Before Scaleout ---")
print(f"Total Exits: {len(before)}")
print(f"Total PNL (USDT): {before['수익(USDT)'].sum():.4f}")

print(f"--- After Scaleout ---")
print(f"Total Exits: {len(after)}")
print(f"Total PNL (USDT): {after['수익(USDT)'].sum():.4f}")

