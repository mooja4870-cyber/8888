import ccxt.async_support as ccxt_async
import asyncio
import traceback

async def test():
    exchange = ccxt_async.okx({
        'options': {
            'adjustForTimeDifference': True,
            'fetchMarkets': ['swap'],
        },
        'enableRateLimit': True,
    })
    try:
        await exchange.load_markets()
        res = await exchange.fetch_tickers(params={'instType': 'SWAP'})
        print(f"Success, got {len(res)} tickers.")
    except Exception as e:
        traceback.print_exc()
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(test())
