import os
import sys
import json
import asyncio
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

CORE_BOTS = [8401, 8402, 8407, 8409, 8410]
ALL_BOTS = [8401, 8402, 8407, 8409, 8410, 8403, 8404, 8405]

async def audit_single_bot(b):
    cwd = f"/Users/l/project/{b}"
    if not os.path.exists(cwd):
        return {"error": "CWD_NOT_FOUND"}

    # Load config
    cfg = {}
    cfg_file = os.path.join(cwd, "config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file) as f: cfg = json.load(f)
        except: pass

    ex_id = cfg.get("EXCHANGE_ID", "okx" if b <= 8405 else "binance").lower()

    # Clear env keys
    for k in ["OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE", "BINANCE_API_KEY", "BINANCE_SECRET_KEY", "BINANCE_PASSPHRASE"]:
        os.environ.pop(k, None)

    # Load api keys from bot directory
    if os.path.exists(os.path.join(cwd, "core", "api_keys.py")):
        sys.path.insert(0, cwd)
        import core.api_keys
        core.api_keys.load_api_keys(override=True)

    client = None
    balance = {}
    ex_positions = {}
    open_orders = []
    fetch_err = None

    try:
        if ex_id == "okx":
            from core.exchange import OKXClient
            client = OKXClient(os.getenv("OKX_API_KEY"), os.getenv("OKX_SECRET_KEY"), os.getenv("OKX_PASSPHRASE"))
        else:
            from core.exchange import BinanceClient
            client = BinanceClient(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"), os.getenv("BINANCE_PASSPHRASE"))
        
        await client.load_markets()
        balance = await client.get_balance()
        raw_positions = await client.get_positions()
        open_orders = await client.get_open_orders()

        for p in raw_positions:
            cnt = float(p.get("size") or p.get("contracts") or p.get("amount") or 0.0)
            if abs(cnt) > 0:
                sym = p.get("symbol")
                ex_positions[sym] = {
                    "symbol": sym,
                    "side": p.get("side"),
                    "size": cnt,
                    "entry_price": float(p.get("entry_price") or p.get("entryPrice") or 0.0),
                    "mark_price": float(p.get("mark_price") or p.get("markPrice") or 0.0),
                    "pnl_pct": float(p.get("pnl_pct") or 0.0),
                    "pnl_usdt": float(p.get("pnl_usdt") or p.get("unrealizedPnl") or 0.0),
                    "leverage": p.get("leverage"),
                }
        await client.close()
    except Exception as e:
        fetch_err = str(e)
    finally:
        if cwd in sys.path:
            sys.path.remove(cwd)
        for m in list(sys.modules.keys()):
            if m.startswith("core"):
                del sys.modules[m]

    # Local ledger positions
    local_pos = {}
    pos_file = os.path.join(cwd, "data", "active_positions.json")
    if os.path.exists(pos_file):
        try:
            with open(pos_file) as f: local_pos = json.load(f)
        except: pass

    # Stats
    stats = {}
    stats_file = os.path.join(cwd, "data", "stats.json")
    if os.path.exists(stats_file):
        try:
            with open(stats_file) as f: stats = json.load(f)
        except: pass

    # Engine log last lines
    engine_log = os.path.join(cwd, "bot_engine.log")
    last_log_lines = []
    last_mtime = None
    if os.path.exists(engine_log):
        last_mtime = datetime.fromtimestamp(os.path.getmtime(engine_log), tz=KST)
        try:
            with open(engine_log, "r", errors="ignore") as f:
                lines = f.readlines()
                last_log_lines = [l.strip() for l in lines[-20:] if l.strip()]
        except: pass

    # Scanner candidates
    scan_file = os.path.join(cwd, "data", "scanner_results.json")
    scan_results = []
    if os.path.exists(scan_file):
        try:
            with open(scan_file) as f: scan_results = json.load(f)
        except: pass

    return {
        "bot": b,
        "is_core": b in CORE_BOTS,
        "exchange": ex_id,
        "config": cfg,
        "balance": balance,
        "ex_positions": ex_positions,
        "open_orders": open_orders,
        "local_positions": local_pos,
        "stats": stats,
        "last_mtime": last_mtime,
        "last_log_lines": last_log_lines,
        "scan_results": scan_results,
        "error": fetch_err
    }

async def main():
    results = []
    for b in ALL_BOTS:
        res = await audit_single_bot(b)
        results.append(res)

    print(json.dumps(results, default=str))

asyncio.run(main())
