import asyncio
import sys
import os

async def audit_bot(bot_id):
    bot_dir = f"/Users/l/project/{bot_id}"
    sys.path.insert(0, bot_dir)
    try:
        from core.exchange import OKXClient
        from core.config import Config
        
        cfg = Config()
        client = OKXClient(cfg)
        
        positions = await client.get_positions()
        
        # Accessing private method for open orders if exists, or using ccxt directly
        # Some bots might have `client.exchange.fetch_open_orders()`
        try:
            orders = await asyncio.to_thread(client.exchange.fetch_open_orders)
        except:
            orders = []
            
        if not positions:
            return f"[{bot_id}] 무포지션"
            
        res = []
        for p in positions:
            sym = p['symbol']
            side = p['side']
            amt = p['amount']
            
            # find matching orders
            sym_orders = [o for o in orders if o['symbol'] == sym]
            sl_orders = [o for o in sym_orders if o.get('type') == 'stop_market' or 'stop' in str(o.get('type')).lower()]
            tp_orders = [o for o in sym_orders if o.get('type') == 'limit' or 'take_profit' in str(o.get('type')).lower()]
            
            sl_info = "O" if sl_orders else "X"
            tp_info = "O" if tp_orders else "X"
            
            # Check trailing stop logs in bot_engine.log
            log_path = os.path.join(bot_dir, 'bot_engine.log')
            trailing_active = "X"
            try:
                with open(log_path, 'r') as logf:
                    tail = logf.readlines()[-500:]
                    for line in tail:
                        if sym in line and ("TRAILING" in line or "트레일링" in line):
                            trailing_active = "O"
                            break
            except:
                pass
                
            res.append(f"[{bot_id}] {sym} {side} {amt} | 거래소보호(SL:{sl_info}/TP:{tp_info}) | 트레일링감시:{trailing_active}")
            
        return "\n".join(res)
    except Exception as e:
        return f"[{bot_id}] 오류: {e}"
    finally:
        sys.path.pop(0)

async def main():
    for i in range(8401, 8411):
        res = await audit_bot(i)
        print(res)

if __name__ == "__main__":
    asyncio.run(main())
