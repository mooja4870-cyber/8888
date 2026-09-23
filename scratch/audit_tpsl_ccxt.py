import asyncio
import ccxt.async_support as ccxt
import os

async def audit_bot(bot_id):
    bot_dir = f"/Users/l/project/{bot_id}"
    env_path = os.path.join(bot_dir, ".env")
    
    if not os.path.exists(env_path):
        return f"[{bot_id}] .env 없음"
        
    api_key, secret_key, passphrase = None, None, None
    with open(env_path, 'r') as f:
        for line in f:
            if line.startswith("OKX_API_KEY="): api_key = line.split("=")[1].strip()
            if line.startswith("OKX_SECRET_KEY="): secret_key = line.split("=")[1].strip()
            if line.startswith("OKX_PASSPHRASE="): passphrase = line.split("=")[1].strip()
            
    exchange = ccxt.okx({
        'apiKey': api_key,
        'secret': secret_key,
        'password': passphrase,
        'enableRateLimit': True,
    })
    
    try:
        positions = await exchange.fetch_positions()
        positions = [p for p in positions if float(p.get('contracts', 0)) > 0]
        
        if not positions:
            return f"[{bot_id}] 무포지션"
            
        orders = await exchange.fetch_open_orders()
        
        res = []
        for p in positions:
            sym = p['symbol']
            side = p['side']
            amt = p['contracts']
            entry = p['entryPrice']
            
            sym_orders = [o for o in orders if o['symbol'] == sym]
            
            sl_orders = [o for o in sym_orders if o.get('stopLossPrice') or o.get('type') == 'stop_market' or 'stop' in str(o.get('type', '')).lower()]
            tp_orders = [o for o in sym_orders if o.get('takeProfitPrice') or o.get('type') == 'limit' or 'take_profit' in str(o.get('type', '')).lower()]
            
            sl_info = "O" if sl_orders else "X"
            tp_info = "O" if tp_orders else "X"
            
            # log check
            log_path = os.path.join(bot_dir, 'bot_engine.log')
            trailing = "X"
            try:
                with open(log_path, 'r') as logf:
                    tail = logf.readlines()[-2000:]
                    for line in tail:
                        if sym in line and ("TRAILING" in line or "트레일링" in line or "락인 해제" in line):
                            trailing = "O"
                            break
            except: pass
            
            res.append(f"[{bot_id}] {sym} {side.upper()} 진입가:{entry} 수량:{amt} | TP:{tp_info} SL:{sl_info} | 트레일링발동:{trailing}")
            
        return "\n".join(res)
    except Exception as e:
        return f"[{bot_id}] 에러: {e}"
    finally:
        await exchange.close()

async def main():
    for i in range(8401, 8411):
        res = await audit_bot(i)
        print(res)

if __name__ == "__main__":
    asyncio.run(main())
