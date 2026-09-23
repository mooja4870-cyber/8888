import sys

file_path = "/Users/l/project/8404/bot.py"
with open(file_path, "r") as f:
    content = f.read()

# Replace client import
content = content.replace("from core.exchange import BinanceClient\n    from core.scanner import Scanner", 
                          "from core.exchange import BinanceClient, OKXClient\n    from core.scanner import Scanner")

# Replace connection block
old_block = """    # ── API 연결 ─────────────────────────────────────────
    logger.info("▶ Binance API 연결 중...")
    client = BinanceClient(api_key, secret_key, passphrase)
    if not await client.load_markets():
        logger.error("❌ 마켓 로드 실패")
        return
    logger.info("✅ Binance API 연결 성공")"""

new_block = """    # ── API 연결 ─────────────────────────────────────────
    if str(CFG.EXCHANGE_ID).lower() == "okx":
        logger.info("▶ OKX API 연결 중...")
        client = OKXClient(api_key, secret_key, passphrase)
    else:
        logger.info("▶ Binance API 연결 중...")
        client = BinanceClient(api_key, secret_key, passphrase)

    if not await client.load_markets():
        logger.error("❌ 마켓 로드 실패")
        return
    logger.info("✅ API 연결 성공")"""

content = content.replace(old_block, new_block)

with open(file_path, "w") as f:
    f.write(content)

print("Patched bot.py")
