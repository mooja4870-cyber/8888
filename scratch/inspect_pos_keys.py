import sys, os, json, asyncio

async def check():
    for b in [8401, 8407]:
        cwd = f"/Users/l/project/{b}"
        sys.path.insert(0, cwd)
        from core.api_keys import load_api_keys
        load_api_keys(override=True)
        if b == 8401:
            from core.exchange import OKXClient
            client = OKXClient(os.getenv("OKX_API_KEY"), os.getenv("OKX_SECRET_KEY"), os.getenv("OKX_PASSPHRASE"))
        else:
            from core.exchange import BinanceClient
            client = BinanceClient(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"), os.getenv("BINANCE_PASSPHRASE"))
        await client.load_markets()
        positions = await client.get_positions()
        await client.close()
        for p in positions:
            cnt = float(p.get("contracts") or p.get("amount") or p.get("size") or 0.0)
            if abs(cnt) > 0:
                print(f"=== BOT {b} RAW POS ===")
                print(json.dumps(p, indent=2))
                break

asyncio.run(check())
