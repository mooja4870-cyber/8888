import os
import subprocess

SOURCE = "/Users/l/project/8410"

def rsync_bot(target, exchange):
    print(f"▶ Rsync 8410 -> {target} ...")
    cmd = [
        "rsync", "-a", "--delete",
        "--exclude=.env",
        "--exclude=.git",
        "--exclude=venv",
        "--exclude=run.sh",
        "--exclude=run_bot.sh",
        "--exclude=api.md",
        "--exclude=*.log",
        "--exclude=logs/",
        "--exclude=data/",
        "--exclude=scratch/",
        "--exclude=__pycache__/",
        f"{SOURCE}/", f"/Users/l/project/{target}/"
    ]
    subprocess.run(cmd, check=True)

    # 1. Update EXCHANGE_ID
    config_path = f"/Users/l/project/{target}/config.json"
    with open(config_path, "r") as f:
        content = f.read()
    import re
    content = re.sub(r'"EXCHANGE_ID":\s*"[^"]*"', f'"EXCHANGE_ID": "{exchange}"', content)
    with open(config_path, "w") as f:
        f.write(content)
        
    # 2. Patch run.sh labels if needed
    run_path = f"/Users/l/project/{target}/run.sh"
    with open(run_path, "r") as f:
        r_content = f.read()
    r_content = r_content.replace("8410", target).replace("8410_binance", f"{target}_{exchange}").replace(f"{target}_binance", f"{target}_{exchange}")
    with open(run_path, "w") as f:
        f.write(r_content)

def patch_okx_bot(target):
    print(f"▶ Patching OKX specific code for {target} ...")
    # Patch bot.py
    bot_path = f"/Users/l/project/{target}/bot.py"
    with open(bot_path, "r") as f:
        content = f.read()
    content = content.replace("from core.exchange import BinanceClient\n    from core.scanner import Scanner", 
                              "from core.exchange import BinanceClient, OKXClient\n    from core.scanner import Scanner")
    old_env = """    api_key    = os.getenv("BINANCE_API_KEY", "")
    secret_key = os.getenv("BINANCE_SECRET_KEY", "")
    passphrase = os.getenv("BINANCE_PASSPHRASE", "")"""
    new_env = """    if str(CFG.EXCHANGE_ID).lower() == "okx":
        api_key    = os.getenv("OKX_API_KEY", "")
        secret_key = os.getenv("OKX_SECRET_KEY", "")
        passphrase = os.getenv("OKX_PASSPHRASE", "")
    else:
        api_key    = os.getenv("BINANCE_API_KEY", "")
        secret_key = os.getenv("BINANCE_SECRET_KEY", "")
        passphrase = os.getenv("BINANCE_PASSPHRASE", "")"""
    content = content.replace(old_env, new_env)
    
    old_inst = """    # ── API 연결 ─────────────────────────────────────────
    logger.info("▶ Binance API 연결 중...")
    client = BinanceClient(api_key, secret_key, passphrase)
    if not await client.load_markets():
        logger.error("❌ 마켓 로드 실패")
        return
    logger.info("✅ Binance API 연결 성공")"""
    new_inst = """    # ── API 연결 ─────────────────────────────────────────
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
    content = content.replace(old_inst, new_inst)
    with open(bot_path, "w") as f:
        f.write(content)

    # Patch app.py
    app_path = f"/Users/l/project/{target}/app.py"
    with open(app_path, "r") as f:
        content = f.read()
    content = content.replace('os.getenv("BINANCE_API_KEY", "")', 'os.getenv("OKX_API_KEY", "") if str(CFG.EXCHANGE_ID).lower()=="okx" else os.getenv("BINANCE_API_KEY", "")')
    content = content.replace('os.getenv("BINANCE_SECRET_KEY", "")', 'os.getenv("OKX_SECRET_KEY", "") if str(CFG.EXCHANGE_ID).lower()=="okx" else os.getenv("BINANCE_SECRET_KEY", "")')
    content = content.replace('os.getenv("BINANCE_PASSPHRASE", "")', 'os.getenv("OKX_PASSPHRASE", "") if str(CFG.EXCHANGE_ID).lower()=="okx" else os.getenv("BINANCE_PASSPHRASE", "")')
    with open(app_path, "w") as f:
        f.write(content)

    # Patch engine.py
    engine_path = f"/Users/l/project/{target}/core/engine.py"
    with open(engine_path, "r") as f:
        content = f.read()
    content = content.replace('from core.exchange import BinanceClient', 'from core.exchange import BinanceClient, OKXClient')
    old_inst_e = 'self.client = BinanceClient(api_key, secret_key, passphrase)'
    new_inst_e = '''if str(CFG.EXCHANGE_ID).lower() == "okx":
                    self.client = OKXClient(api_key, secret_key, passphrase)
                else:
                    self.client = BinanceClient(api_key, secret_key, passphrase)'''
    content = content.replace(old_inst_e, new_inst_e)
    with open(engine_path, "w") as f:
        f.write(content)

def replace_labels(target, exchange):
    print(f"▶ Replacing labels in {target} ...")
    files_to_patch = [
        f"/Users/l/project/{target}/app.py",
        f"/Users/l/project/{target}/bot.py",
        f"/Users/l/project/{target}/core/config.py",
        f"/Users/l/project/{target}/core/regime_router.py",
        f"/Users/l/project/{target}/core/trader.py"
    ]
    for fp in files_to_patch:
        if os.path.exists(fp):
            with open(fp, "r") as f:
                content = f.read()
            content = content.replace("8410_binance", f"{target}_{exchange}")
            content = content.replace("8410", target)
            with open(fp, "w") as f:
                f.write(content)

def patch_btc_symbol(target):
    print(f"▶ Patching BTC/USDT hardcoding in {target} ...")
    tsm_path = f"/Users/l/project/{target}/core/trailing_stop_manager.py"
    if os.path.exists(tsm_path):
        with open(tsm_path, "r") as f:
            content = f.read()
        content = content.replace('await self.engine.client.get_ohlcv("BTC/USDT", timeframe=\'15m\', limit=25)', 
                                  'await self.engine.client.get_ohlcv(str(CFG.REGIME_REF_SYMBOL), timeframe=\'15m\', limit=25)')
        content = content.replace('if sym != "BTC/USDT" and btc_step > new_step:', 
                                  'if sym != str(CFG.REGIME_REF_SYMBOL) and btc_step > new_step:')
        with open(tsm_path, "w") as f:
            f.write(content)

# Process 8406 (OKX)
print("=== 8406 (OKX) 이식 ===")
rsync_bot("8406", "okx")
patch_okx_bot("8406")
replace_labels("8406", "okx")
patch_btc_symbol("8406")

# Process 8408 (Binance)
print("\n=== 8408 (Binance) 이식 ===")
rsync_bot("8408", "binance")
replace_labels("8408", "binance")
patch_btc_symbol("8408")

# Process 8404 (OKX) - just the BTC symbol fix
print("\n=== 8404 (OKX) 추가 패치 ===")
patch_btc_symbol("8404")

print("\nAll patching done!")
