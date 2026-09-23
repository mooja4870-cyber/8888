import asyncio
import ccxt.async_support as ccxt
import os

async def main():
    exchange = ccxt.okx({'enableRateLimit': True})
    await exchange.load_markets()
    market = exchange.market("UNI/USDT:USDT")
    print(f"Contract Size: {market.get('contractSize')}")
    print(f"Limits: {market.get('limits')}")
    
    amount = 3.30 / (6.5 * 1.0) # 0.507
    print(f"Raw amount: {amount}")
    
    prec_amount = exchange.amount_to_precision("UNI/USDT:USDT", amount)
    print(f"Precision amount: {prec_amount}")
    
    min_amount = market.get('limits', {}).get('amount', {}).get('min', 0.0)
    print(f"min_amount: {min_amount}")
    if min_amount and float(prec_amount) < float(min_amount):
        print("Blocked by min_amount check!")
    else:
        print("Passed min_amount check!")
        
    await exchange.close()

asyncio.run(main())
