import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import asyncio

async def fetch_klines(symbol, timeframe, days):
    exchange = ccxt.binance()
    since = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    all_ohlcv = []
    
    print(f"Fetching {days} days of {timeframe} data for {symbol}...")
    while True:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since, limit=1000)
            if not ohlcv:
                break
            all_ohlcv.extend(ohlcv)
            since = ohlcv[-1][0] + 1
            if len(ohlcv) < 1000:
                break
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(2)
            
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

def calc_bb_mr(df, rsi_period=14, bb_period=20, bb_std=2.0):
    # Bollinger Bands
    sma = df['close'].rolling(window=bb_period).mean()
    std = df['close'].rolling(window=bb_period).std()
    df['up'] = sma + (std * bb_std)
    df['dn'] = sma - (std * bb_std)
    df['sma'] = sma
    
    # ATR
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/rsi_period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/rsi_period, adjust=False).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def run_backtest(df, rsi_thresh, sl_mult, tp_mult=1.0):
    balance = 100.0
    position = 0
    entry_price = 0
    sl_price = 0
    tp_price = 0
    
    trades = []
    peak_balance = balance
    mdd = 0.0
    
    for i in range(20, len(df)):
        c = df['close'].iloc[i]
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        
        # Check Stop Loss / Take Profit
        if position != 0:
            exit_price = 0
            is_sl = False
            
            if position == 1:
                if l <= sl_price:
                    exit_price = sl_price
                    is_sl = True
                elif h >= tp_price:
                    exit_price = tp_price
            elif position == -1:
                if h >= sl_price:
                    exit_price = sl_price
                    is_sl = True
                elif l <= tp_price:
                    exit_price = tp_price
            
            if exit_price != 0:
                pnl_pct = (exit_price - entry_price) / entry_price * position
                pnl = balance * 3 * pnl_pct  # 3x leverage
                balance += pnl
                trades.append(1 if pnl > 0 else -1)
                
                if balance > peak_balance:
                    peak_balance = balance
                else:
                    dd = (peak_balance - balance) / peak_balance
                    if dd > mdd:
                        mdd = dd
                        
                position = 0
                continue
        
        # Check Entry
        if position == 0:
            c_prev = df['close'].iloc[i-1]
            dn = df['dn'].iloc[i-1]
            up = df['up'].iloc[i-1]
            rsi = df['rsi'].iloc[i-1]
            atr = df['atr'].iloc[i-1]
            sma = df['sma'].iloc[i-1]
            
            if pd.isna(c_prev) or pd.isna(dn):
                continue
                
            if c_prev < dn and rsi < rsi_thresh:
                position = 1
                entry_price = c
                sl_price = c - (atr * sl_mult)
                tp_price = sma
                if tp_price <= c: tp_price = c + (atr * tp_mult)
            elif c_prev > up and rsi > (100 - rsi_thresh):
                position = -1
                entry_price = c
                sl_price = c + (atr * sl_mult)
                tp_price = sma
                if tp_price >= c: tp_price = c - (atr * tp_mult)

    wins = trades.count(1)
    total = len(trades)
    win_rate = (wins / total * 100) if total > 0 else 0
    return balance, mdd * 100, win_rate, total

async def main():
    coins = ["SOL/USDT", "DOGE/USDT", "XRP/USDT"]
    for coin in coins:
        df = await fetch_klines(coin, "15m", 180)
        df = calc_bb_mr(df)
        
        print(f"\n--- {coin} (15m, 180 Days) ---")
        best_bal = 0
        best_p = None
        
        for rsi in [30, 35]:
            for sl in [2.0, 2.5, 3.0, 4.0]:
                bal, mdd, wr, tot = run_backtest(df, rsi, sl)
                if bal > best_bal:
                    best_bal = bal
                    best_p = (rsi, sl, mdd, wr, tot)
                
                # print(f"RSI<{rsi}, SL={sl}x => Bal: {bal:.2f}, MDD: {mdd:.1f}%, WR: {wr:.1f}% ({tot})")
        
        print(f"⭐ BEST: RSI<{best_p[0]}, SL={best_p[1]}x => Bal: {best_bal:.2f}, MDD: {best_p[2]:.1f}%, WR: {best_p[3]:.1f}% (Trades: {best_p[4]})")

if __name__ == "__main__":
    asyncio.run(main())
