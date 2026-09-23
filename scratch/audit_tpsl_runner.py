import asyncio
import sys
import os

async def main():
    try:
        from core.config import settings, Config
        cfg = settings if 'settings' in locals() else Config()
    except ImportError:
        import json
        with open('config.json', 'r') as f:
            cfg_dict = json.load(f)
        # Mock cfg object
        class Cfg:
            pass
        cfg = Cfg()
        for k, v in cfg_dict.items():
            setattr(cfg, k, v)
            
    try:
        from core.exchange import OKXClient
        client = OKXClient(cfg)
    except ImportError:
        from core.exchange import ExchangeClient
        client = ExchangeClient(cfg)

    positions = await client.get_positions()
    try:
        orders = await asyncio.to_thread(client.exchange.fetch_open_orders)
    except:
        try:
            orders = await client._fetch_open_orders()
        except:
            orders = []

    bot_id = os.getcwd()[-4:]
    if not positions:
        print(f"[{bot_id}] 무포지션")
        return

    res = []
    for p in positions:
        sym = p['symbol']
        side = p['side']
        amt = p['amount']
        
        sym_orders = [o for o in orders if o['symbol'] == sym]
        sl_orders = [o for o in sym_orders if o.get('type') == 'stop_market' or 'stop' in str(o.get('type')).lower()]
        tp_orders = [o for o in sym_orders if o.get('type') == 'limit' or 'take_profit' in str(o.get('type')).lower()]
        
        sl_info = "O" if sl_orders else "X"
        tp_info = "O" if tp_orders else "X"
        
        log_path = 'bot_engine.log'
        trailing_active = "X"
        try:
            with open(log_path, 'r') as logf:
                tail = logf.readlines()[-1000:]
                for line in tail:
                    if sym in line and ("TRAILING" in line or "트레일링" in line):
                        trailing_active = "O"
                        break
        except:
            pass
            
        res.append(f"[{bot_id}] {sym} {side} {amt} | 거래소보호(SL:{sl_info}/TP:{tp_info}) | 트레일링:{trailing_active}")
        
    print("\n".join(res))

if __name__ == "__main__":
    asyncio.run(main())
