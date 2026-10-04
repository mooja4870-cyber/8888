import os

BOT_PORTS = ["8401", "8402", "8403", "8404", "8405", "8408", "8410"]
BASE_DIR = "/Users/l/project"

TARGET = "raw_tickers = await self._execute_with_retry(self.exchange.fetch_tickers)"
REPLACE = "raw_tickers = await self._execute_with_retry(self.exchange.fetch_tickers, params={\"instType\": \"SWAP\"})"

for port in BOT_PORTS:
    bot_dir = os.path.join(BASE_DIR, port)
    exchange_path = os.path.join(bot_dir, "core", "exchange.py")
    
    if os.path.exists(exchange_path):
        with open(exchange_path, "r") as f:
            content = f.read()
        
        if TARGET in content:
            new_content = content.replace(TARGET, REPLACE)
            with open(exchange_path, "w") as f:
                f.write(new_content)
            print(f"Patched {port} exchange.py (fetch_tickers SWAP fix)")
        else:
            print(f"Target not found in {port} exchange.py")
    else:
        print(f"File not found: {exchange_path}")
