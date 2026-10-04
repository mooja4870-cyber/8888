import sys, os, asyncio
sys.path.append('/Users/l/project/8404')
from dotenv import load_dotenv
load_dotenv('/Users/l/project/8404/.env')
from core.exchange import OKXClient

async def main():
    client = OKXClient(
        os.getenv('OKX_API_KEY'),
        os.getenv('OKX_SECRET_KEY'),
        os.getenv('OKX_PASSPHRASE')
    )
    positions = await client.get_positions()
    for p in positions:
        sym = p.get("symbol")
        side = p.get("side")
        entry_price = float(p.get("entry_price") or 0.0)
        mark_price = float(p.get("mark_price") or 0.0)
        if entry_price > 0 and mark_price > 0:
            pnl_pct = (mark_price - entry_price) / entry_price if side == "long" else (entry_price - mark_price) / entry_price
            print(f"{sym} {side} - Entry: {entry_price}, Mark: {mark_price}, PnL: {pnl_pct*100}%")
            
    await client.exchange.close()

asyncio.run(main())
