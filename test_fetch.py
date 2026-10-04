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
    raw = await client.exchange.fetch_tickers(params={"instType": "SWAP"})
    print(f"Got {len(raw)} tickers!")
    await client.exchange.close()

asyncio.run(main())
