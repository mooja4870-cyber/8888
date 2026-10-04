import ccxt
import pandas as pd
import numpy as np
import time
import os
from datetime import datetime, timedelta

def fetch_data(symbol="SOL/USDT", timeframe="1h", days=180):
    filename = f"{symbol.replace('/', '_')}_{timeframe}_{days}d.csv"
    if os.path.exists(filename):
        df = pd.read_csv(filename)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df

    print(f"Fetching {days} days of {timeframe} data for {symbol}...")
    exchange = ccxt.binance()
    end_time = exchange.milliseconds()
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    
    all_ohlcv = []
    current_time = start_time
    
    while current_time < end_time:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=current_time, limit=1000)
            if not ohlcv:
                break
            all_ohlcv.extend(ohlcv)
            current_time = ohlcv[-1][0] + 1
            time.sleep(0.1)
        except Exception as e:
            print(f"Error fetching data: {e}")
            time.sleep(2)
            
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.drop_duplicates(subset=['timestamp'], inplace=True)
    df.to_csv(filename, index=False)
    return df

def add_indicators(df, tsmom_lookback=30, bb_period=20, bb_std=2.0):
    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['atr'] = true_range.rolling(14).mean()
    
    # TSMOM (Donchian)
    df['donchian_high'] = df['high'].rolling(tsmom_lookback).max().shift(1)
    df['donchian_low'] = df['low'].rolling(tsmom_lookback).min().shift(1)
    
    # BBTS
    df['bb_mid'] = df['close'].rolling(bb_period).mean()
    df['bb_std'] = df['close'].rolling(bb_period).std()
    df['bb_upper'] = df['bb_mid'] + bb_std * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - bb_std * df['bb_std']
    
    return df

def backtest(df, strategy="tsmom", sl_mult=2.0, tp_mult=2.0, leverage=3, risk_pct=0.05):
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
            
            direction = 0
            if strategy == "tsmom":
                hh = df['donchian_high'].iloc[i-1]
                ll = df['donchian_low'].iloc[i-1]
                if c > hh: direction = 1
                elif c < ll: direction = -1
            elif strategy == "bbts":
                up = df['bb_upper'].iloc[i-1]
                dn = df['bb_lower'].iloc[i-1]
                if c > up: direction = 1
                elif c < dn: direction = -1
                
            if direction != 0:
                position = direction
                entry_price = df['open'].iloc[i]
                if direction == 1:
                    sl_price = entry_price - (atr * sl_mult)
                    tp_price = entry_price + (atr * tp_mult)
                else:
                    sl_price = entry_price + (atr * sl_mult)
                    tp_price = entry_price - (atr * tp_mult)
                    
        elif position != 0:
            low = df['low'].iloc[i]
            high = df['high'].iloc[i]
            
            closed = False
            pnl_pct = 0.0
            
            if position == 1:
                if low <= sl_price:
                    pnl_pct = (sl_price - entry_price) / entry_price
                    closed = True
                elif high >= tp_price:
                    pnl_pct = (tp_price - entry_price) / entry_price
                    closed = True
            elif position == -1:
                if high >= sl_price:
                    pnl_pct = (entry_price - sl_price) / entry_price
                    closed = True
                elif low <= tp_price:
                    pnl_pct = (entry_price - tp_price) / entry_price
                    closed = True
                    
            if closed:
                raw_pnl = pnl_pct * leverage
                sl_pct = abs(entry_price - sl_price) / entry_price
                if sl_pct > 0:
                    margin = (balance * risk_pct) / (sl_pct * leverage)
                    margin = min(margin, balance * 0.3)
                    pnl_usdt = margin * raw_pnl * leverage
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

coins = ["SOL/USDT", "ETH/USDT", "XRP/USDT", "DOGE/USDT"]
results = []
for coin in coins:
    df = fetch_data(symbol=coin, timeframe="1h", days=180)
    df = add_indicators(df, tsmom_lookback=30, bb_period=20, bb_std=2.0)
    
    for st in ["tsmom", "bbts"]:
        for tp in [2.0, 3.0, 4.0]:
            bal, mdd, trd, wr = backtest(df, strategy=st, sl_mult=2.0, tp_mult=tp)
            results.append((coin, st, tp, bal, mdd, trd, wr))
            
for r in results:
    print(f"Coin: {r[0]:<10} | Strat: {r[1]:<5} | TP: {r[2]}x | Bal: {r[3]:.2f} | MDD: {r[4]:.2f}% | Trd: {r[5]} | WR: {r[6]:.2f}%")
