import ccxt
import pandas as pd
import numpy as np
import time
import os
from datetime import datetime, timedelta

def fetch_data(symbol="SOL/USDT", timeframe="5m", days=180):
    filename = f"{symbol.replace('/', '_')}_{timeframe}_{days}d.csv"
    if os.path.exists(filename):
        print(f"Loading {filename} from cache...")
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
    print(f"Saved {len(df)} rows to {filename}")
    return df

def add_indicators(df):
    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['atr'] = true_range.rolling(14).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Bollinger Bands
    df['bb_mid'] = df['close'].rolling(20).mean()
    df['bb_std'] = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2.0 * df['bb_std']
    df['bb_lower'] = df['bb_mid'] - 2.0 * df['bb_std']
    
    return df

def backtest_strategy_4(df, rsi_thresh=30, sl_mult=1.5, verbose=False):
    if verbose:
        print(f"\n--- Running Backtest: BB Mean Reversion (RSI<{rsi_thresh}, SL={sl_mult}x) ---")
    df = df.dropna().reset_index(drop=True)
    
    initial_balance = 100.0
    balance = initial_balance
    position = 0
    entry_price = 0
    sl_price = 0
    tp_price = 0
    
    trades = 0
    wins = 0
    losses = 0
    peak_balance = initial_balance
    mdd = 0.0
    
    leverage = 3
    risk_pct = 0.05
    
    bars_held = 0
    
    for i in range(2, len(df)):
        if position == 0:
            # Entry condition: Close < BB Lower AND RSI < thresh
            bb_out = df['close'].iloc[i-1] < df['bb_lower'].iloc[i-1]
            rsi_ok = df['rsi'].iloc[i-1] < rsi_thresh
            
            if bb_out and rsi_ok:
                position = 1
                entry_price = df['open'].iloc[i]
                atr = df['atr'].iloc[i-1]
                sl_price = entry_price - (atr * sl_mult)
                tp_price = df['bb_mid'].iloc[i-1] # TP is the BB Mid line
                
                # To prevent negative RR if BB Mid is too close
                if tp_price <= entry_price:
                    tp_price = entry_price + (atr * 1.0)
                
                sl_pct = (entry_price - sl_price) / entry_price
                if sl_pct == 0: sl_pct = 0.01
                
                pos_size_usd = (balance * risk_pct) / sl_pct
                if pos_size_usd > balance * leverage:
                    pos_size_usd = balance * leverage
                    
                trades += 1
        elif position == 1:
            if df['low'].iloc[i] <= sl_price:
                loss_pct = (entry_price - sl_price) / entry_price
                balance -= (pos_size_usd * loss_pct)
                balance -= (pos_size_usd * 0.001)
                losses += 1
                position = 0
            elif df['high'].iloc[i] >= tp_price:
                win_pct = (tp_price - entry_price) / entry_price
                balance += (pos_size_usd * win_pct)
                balance -= (pos_size_usd * 0.001)
                wins += 1
                position = 0
                
        if balance > peak_balance:
            peak_balance = balance
        drawdown = (peak_balance - balance) / peak_balance
        if drawdown > mdd:
            mdd = drawdown
            
        if balance <= 0:
            break
            
    win_rate = (wins / trades * 100) if trades > 0 else 0
    pnl_pct = ((balance - initial_balance) / initial_balance) * 100
    
    if verbose:
        print(f"Total Trades: {trades} | Win Rate: {win_rate:.2f}% | Return: {pnl_pct:.2f}% | MDD: {mdd*100:.2f}%")
        
    return pnl_pct, mdd*100, win_rate, trades

def run_optimizer(df):
    print("\n[BB Mean Reversion Grid Search Optimizer Starting...]")
    best_pnl = -999
    best_params = None
    best_metrics = None
    
    for rsi in [25, 30, 35]:
        for sl in [1.0, 1.5, 2.0, 3.0]:
            pnl, mdd, wr, trades = backtest_strategy_4(df, rsi, sl, verbose=False)
            if trades < 5: 
                continue
            if pnl > best_pnl:
                best_pnl = pnl
                best_params = (rsi, sl)
                best_metrics = (pnl, mdd, wr, trades)
                        
    if best_params:
        print("\n🏆 [BEST BB PARAMETERS FOUND]")
        print(f"RSI < {best_params[0]} | SL {best_params[1]}x ATR | TP = BB Mid")
        print(f"Return: {best_metrics[0]:.2f}% | MDD: {best_metrics[1]:.2f}% | Win Rate: {best_metrics[2]:.2f}% | Trades: {best_metrics[3]}")
    else:
        print("No profitable combination found.")

if __name__ == "__main__":
    df = fetch_data("SOL/USDT", "1h", 180) # 1h data for 180 days
    df = add_indicators(df)
    run_optimizer(df)
