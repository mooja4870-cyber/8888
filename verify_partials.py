import pandas as pd

df = pd.read_csv('/Users/l/project/8402/data/trade_history.csv')
df['시간'] = pd.to_datetime(df['시간'])

split_date = pd.to_datetime("2026-09-24 09:12:54")

before = df[(df['시간'] < split_date)]
after = df[(df['시간'] >= split_date)]

def check_partials(name, data):
    partials = data[data['유형'] == '부분청산']
    print(f"--- {name} ---")
    print(f"Total exits: {len(data[data['유형'] == '청산'])}")
    print(f"Total partial exits (부분청산): {len(partials)}")

check_partials("Before Bug Fix (Sep 11 ~ Sep 24)", before)
check_partials("After Bug Fix (Sep 25 ~ Today)", after)
