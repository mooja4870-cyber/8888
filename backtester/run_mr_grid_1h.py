import ccxt
import pandas as pd
import numpy as np
import time
import os

def fetch_data(symbol="SOL/USDT", timeframe="1h", days=180):
    filename = f"{symbol.replace('/', '_')}_{timeframe}_{days}d.csv"
    if os.path.exists(filename):
        df = pd.read_csv(filename)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    return None

def backtest_mr(df, rsi_thresh=35, sl_mult=3.0):
    df = df.dropna().reset_index(drop=True)
    balance = 100.0
    initial_balance = balance
    position = 0
    entry_price = 0
    sl_price = 0
    tp_price = 0
    
    trades, wins, losses = 0, 0, 0
    peak_balance = balance
    mdd = 0.0
    
    for i in range(2, len(df)):
        if position == 0:
            c = df['close'].iloc[i-1]
            atr = df['atr'].iloc[i-1]
            
            bb_out = c < df['bb_lower'].iloc[i-1]
            rsi_ok = df['rsi'].iloc[i-1] < rsi_thresh
            
            if bb_out and rsi_ok:
                position = 1
                entry_price = df['open'].iloc[i]
                sl_price = entry_price - (atr * sl_mult)
                tp_price = df['bb_mid'].iloc[i-1]
                if tp_price <= entry_price:
                    tp_price = entry_price + (atr * 1.5)
                    
        elif position != 0:
            low = df['low'].iloc[i]
            high = df['high'].iloc[i]
            
            closed = False
            pnl_pct = 0.0
            
            if low <= sl_price:
                pnl_pct = (sl_price - entry_price) / entry_price
                closed = True
            elif high >= tp_price:
                pnl_pct = (tp_price - entry_price) / entry_price
                closed = True
                
            if closed:
                raw_pnl = pnl_pct * 3 # leverage 3
                sl_pct = abs(entry_price - sl_price) / entry_price
                if sl_pct > 0:
                    margin = (balance * 0.05) / (sl_pct * 3)
                    margin = min(margin, balance * 0.3)
                    pnl_usdt = margin * raw_pnl * 3
                    balance += pnl_usdt
                
                trades += 1
                if pnl_pct > 0: wins += 1
                else: losses += 1
                
                if balance > peak_balance: peak_balance = balance
                dd = (peak_balance - balance) / peak_balance
                if dd > mdd: mdd = dd
                
                position = 0
                
    wr = (wins / trades * 100) if trades > 0 else 0
    return balance, mdd * 100, trades, wr

def add_indicators(df):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['atr'] = true_range.rolling(14).mean()
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    df['bb_mid'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2.0 * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - 2.0 * df['bb_std']
    return df

coins = ["SOL/USDT", "ETH/USDT", "XRP/USDT", "DOGE/USDT"]
for coin in coins:
    df = fetch_data(symbol=coin)
    if df is not None:
        df = add_indicators(df)
        for rsi in [30, 35, 40]:
            for sl in [2.0, 3.0, 4.0]:
                bal, mdd, trd, wr = backtest_mr(df, rsi_thresh=rsi, sl_mult=sl)
                print(f"Coin: {coin:<10} | Strat: BB_MR | RSI<{rsi} | SL={sl}x | Bal: {bal:.2f} | MDD: {mdd:.2f}% | Trd: {trd} | WR: {wr:.2f}%")
