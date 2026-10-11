import pandas as pd
df = pd.read_csv('/Users/l/project/8402/data/trade_history.csv')
df_exit = df[df['유형'].isin(['청산', '부분청산'])]
recent = df_exit.tail(12)
print("--- Recent 12 Trades ---")
print(recent[['시간', '심볼', '방향', '수익률(%)', '청산유형']])

wins = sum(recent['수익률(%)'] > 0)
losses = sum(recent['수익률(%)'] <= 0)
print(f"\nWins: {wins}, Losses: {losses}")
