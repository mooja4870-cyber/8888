import sys, os, json, asyncio

core_bots = [8401, 8402, 8407, 8409, 8410]

async def check_bot(b):
    cwd = f"/Users/l/project/{b}"
    sys.path.insert(0, cwd)
    
    cfg_file = os.path.join(cwd, "config.json")
    ex_id = "binance"
    if os.path.exists(cfg_file):
        with open(cfg_file, "r") as f:
            cfg = json.load(f)
            ex_id = cfg.get("EXCHANGE_ID", "binance").lower()
            strat_name = cfg.get("STRATEGY_NAME", "Unknown")
            tf = cfg.get("TIMEFRAME", "1d")
            lev = cfg.get("LEVERAGE", 10)
            margin = cfg.get("MARGIN_USDT", 10)
            max_pos = cfg.get("MAX_POSITIONS", 3)
    else:
        cfg = {}
        strat_name = "Unknown"
        tf = "Unknown"
        lev = 10
        margin = 10
        max_pos = 3

    # Load API keys
    from core.api_keys import load_api_keys
    load_api_keys(override=True)

    if ex_id == "okx":
        from core.exchange import OKXClient
        client = OKXClient(os.getenv("OKX_API_KEY"), os.getenv("OKX_SECRET_KEY"), os.getenv("OKX_PASSPHRASE"))
    else:
        from core.exchange import BinanceClient
        client = BinanceClient(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"), os.getenv("BINANCE_PASSPHRASE"))

    await client.load_markets()
    bal = await client.get_balance()
    positions = await client.get_positions()
    await client.close()

    # Load local active positions
    local_pos_path = os.path.join(cwd, "data", "active_positions.json")
    local_pos = {}
    if os.path.exists(local_pos_path):
        with open(local_pos_path, "r") as f:
            local_pos = json.load(f)

    # Load stats
    stats_path = os.path.join(cwd, "data", "stats.json")
    stats = {}
    if os.path.exists(stats_path):
        with open(stats_path, "r") as f:
            stats = json.load(f)

    active_live = []
    for p in positions:
        cnt = float(p.get("contracts") or p.get("amount") or p.get("size") or 0.0)
        if abs(cnt) > 0:
            active_live.append(p)

    return {
        "bot": b,
        "exchange": ex_id.upper(),
        "strategy": strat_name,
        "timeframe": tf,
        "leverage": lev,
        "margin": margin,
        "max_positions": max_pos,
        "wallet_balance": bal.get("total", 0.0),
        "free_balance": bal.get("free", 0.0),
        "positions": active_live,
        "local_pos_count": len(local_pos),
        "stats": stats
    }

async def main():
    print("=== LIVE 5-BOT AUDIT RESULTS ===")
    for b in core_bots:
        try:
            res = await check_bot(b)
            print(f"[{res['bot']}] {res['exchange']} | 전략: {res['strategy']} ({res['timeframe']}) | 레버리지: {res['leverage']}x | 마진: ${res['margin']}")
            print(f"  💰 지갑 잔고: 총 ${res['wallet_balance']:.4f} USDT (가용: ${res['free_balance']:.4f})")
            print(f"  📊 실전 전적: {res['stats'].get('wins', 0)}승 {res['stats'].get('losses', 0)}패 (누적 실현손익: {res['stats'].get('total_realized_pnl', 0):+.4f} USDT)")
            
            pos_list = res['positions']
            if pos_list:
                print(f"  🎯 활성 포지션 ({len(pos_list)}건):")
                for p in pos_list:
                    sym = p.get('symbol')
                    side = p.get('side', '').upper()
                    entry = p.get('entryPrice')
                    mark = p.get('markPrice')
                    contracts = p.get('contracts')
                    pnl = float(p.get('unrealizedPnl') or 0.0)
                    pct = float(p.get('percentage') or 0.0)
                    init_margin = float(p.get('initialMargin') or 0.0)
                    print(f"     • {sym} [{side}] | 수량: {contracts} | 진입가: {entry} | 현재가: {mark} | 미실현손익: {pnl:+.4f} USDT ({pct:+.2f}%) | 증거금: ${init_margin:.2f}")
            else:
                print("  🎯 활성 포지션: 없음 (0건 - 무포지션 대기 중)")
            print()
        except Exception as e:
            print(f"[{b}] Error: {e}\n")

asyncio.run(main())
