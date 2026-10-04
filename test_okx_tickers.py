import ccxt
import asyncio

async def test():
    exchange = ccxt.okx({
        'enableRateLimit': True,
    })
    try:
        tickers = exchange.fetch_tickers()
        print(f"Success! Fetched {len(tickers)} tickers.")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
