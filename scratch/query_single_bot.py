import sys, os, json, asyncio

b = sys.argv[1]
cwd = f"/Users/l/project/{b}"
sys.path.insert(0, cwd)

cfg_file = os.path.join(cwd, "config.json")
with open(cfg_file, "r") as f:
    cfg = json.load(f)

ex_id = cfg.get("EXCHANGE_ID", "binance").lower()
strat = cfg.get("STRATEGY_NAME", "Unknown")
tf = cfg.get("TIMEFRAME", "1d")
lev = cfg.get("LEVERAGE", 10)
margin = cfg.get("MARGIN_USDT", 10)

from core.api_keys import load_api_keys
load_api_keys(override=True)

async def check():
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

    active = []
    for p in positions:
        cnt = float(p.get("size") or p.get("contracts") or p.get("amount") or 0.0)
        if abs(cnt) > 0:
            active.append({
                "symbol": p.get("symbol"),
                "side": (p.get("side") or "").upper(),
                "entry_price": p.get("entry_price") or p.get("entryPrice"),
                "mark_price": p.get("mark_price") or p.get("markPrice"),
                "size": cnt,
                "pnl_usdt": float(p.get("pnl_usdt") or p.get("unrealizedPnl") or 0.0),
                "pnl_pct": float(p.get("pnl_pct") or p.get("percentage") or 0.0),
                "margin": float(p.get("margin") or p.get("initialMargin") or 0.0),
                "leverage": p.get("leverage")
            })

    # Stats
    stats_p = os.path.join(cwd, "data", "stats.json")
    stats = {}
    if os.path.exists(stats_p):
        with open(stats_p, "r") as f:
            stats = json.load(f)

    # Active positions local
    local_p = os.path.join(cwd, "data", "active_positions.json")
    local_pos = {}
    if os.path.exists(local_p):
        with open(local_p, "r") as f:
            local_pos = json.load(f)

    # trade_history closed trades count
    csv_p = os.path.join(cwd, "data", "trade_history.csv")
    csv_cnt = 0
    if os.path.exists(csv_p):
        with open(csv_p, "r", encoding="utf-8-sig") as f:
            csv_cnt = max(0, len(f.readlines()) - 1)

    return {
        "bot": b,
        "exchange": ex_id.upper(),
        "strategy": strat,
        "timeframe": tf,
        "leverage": lev,
        "margin": margin,
        "wallet_balance": bal.get("total", 0.0),
        "free_balance": bal.get("free", 0.0),
        "positions": active,
        "local_positions": local_pos,
        "stats": stats,
        "trade_history_rows": csv_cnt
    }

res = asyncio.run(check())
print(json.dumps(res, ensure_ascii=False))

