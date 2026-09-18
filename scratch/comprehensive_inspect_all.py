import os
import sys
import json
import asyncio
import glob
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

CORE_BOTS = [8401, 8402, 8407, 8409, 8410]
ALL_BOTS = [8401, 8402, 8407, 8409, 8410, 8403, 8404, 8405]

async def main():
    # 1. Exchange Positions via Binance
    sys.path.insert(0, "/Users/l/project/8401")
    from core.api_keys import load_api_keys
    load_api_keys(override=True)
    from core.exchange import BinanceClient
    client = BinanceClient(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"), os.getenv("BINANCE_PASSPHRASE"))
    await client.load_markets()

    balance = await client.get_balance()
    raw_positions = await client.get_positions()
    open_orders = await client.get_open_orders()

    ex_positions = {}
    for p in raw_positions:
        amt = float(p.get("contracts") or p.get("amount") or p.get("size") or 0.0)
        if abs(amt) > 0:
            sym = p.get("symbol")
            ex_positions[sym] = {
                "symbol": sym,
                "side": p.get("side"),
                "contracts": amt,
                "entryPrice": float(p.get("entryPrice") or 0.0),
                "markPrice": float(p.get("markPrice") or 0.0),
                "unrealizedPnl": float(p.get("unrealizedPnl") or 0.0),
                "leverage": p.get("leverage"),
                "initialMargin": float(p.get("initialMargin") or 0.0),
            }

    print("=== [1. BINANCE FUTURES REAL-TIME BALANCE & POSITIONS] ===")
    print(f"Total Balance: ${balance.get('total', 0.0):.2f} | Free Balance: ${balance.get('free', 0.0):.2f} | Used: ${balance.get('used', 0.0):.2f}")
    print(f"Open Positions Count on Exchange: {len(ex_positions)}")
    for sym, p in ex_positions.items():
        print(f"  - {sym}: {p['side'].upper()} {p['contracts']} contracts | Entry: ${p['entryPrice']:.4f} | Mark: ${p['markPrice']:.4f} | uPnL: ${p['unrealizedPnl']:+.4f} (lev={p['leverage']}x)")

    print("\n=== [2. BINANCE OPEN ORDERS (TP/SL COVERAGE)] ===")
    print(f"Total Open Orders Count: {len(open_orders)}")
    for o in open_orders:
        sym = o.get("symbol")
        side = o.get("side")
        otype = o.get("type")
        price = o.get("price") or o.get("stopPrice")
        amt = o.get("amount")
        ro = o.get("reduceOnly")
        print(f"  - {sym} | {side} {otype} | amount={amt} | price/stop={price} | reduceOnly={ro}")

    print("\n=== [3. PER-BOT AUDIT (CORE & SECONDARY)] ===")
    claimed_positions = {} # sym -> bot

    for b in ALL_BOTS:
        b_dir = f"/Users/l/project/{b}"
        print(f"\n--- [BOT {b}] {'(CORE)' if b in CORE_BOTS else '(SECONDARY)'} ---")
        if not os.path.exists(b_dir):
            print(f"Directory not found: {b_dir}")
            continue

        # Check config
        cfg = {}
        cfg_file = os.path.join(b_dir, "config.json")
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, "r") as f:
                    cfg = json.load(f)
            except Exception as e:
                print(f"Config error: {e}")

        # Active positions in local ledger
        pos_file = os.path.join(b_dir, "data", "active_positions.json")
        local_positions = {}
        if os.path.exists(pos_file):
            try:
                with open(pos_file, "r") as f:
                    local_positions = json.load(f)
            except Exception as e:
                print(f"Pos file error: {e}")

        # Stats
        stats_file = os.path.join(b_dir, "data", "stats.json")
        stats = {}
        if os.path.exists(stats_file):
            try:
                with open(stats_file, "r") as f:
                    stats = json.load(f)
            except Exception:
                pass

        # Check recent engine log activity
        engine_log = os.path.join(b_dir, "bot_engine.log")
        last_log_lines = []
        last_log_time = "Unknown"
        if os.path.exists(engine_log):
            mtime = datetime.fromtimestamp(os.path.getmtime(engine_log), tz=KST)
            last_log_time = mtime.strftime("%Y-%m-%d %H:%M:%S")
            try:
                with open(engine_log, "r", errors="ignore") as f:
                    lines = f.readlines()
                    last_log_lines = [line.strip() for line in lines[-10:] if line.strip()]
            except Exception:
                pass

        print(f"Strategy: {cfg.get('STRATEGY', 'Unknown')} | Timeframe: {cfg.get('TIMEFRAME', 'Unknown')} | Max Pos: {cfg.get('MAX_POSITIONS', 1)} | Max Hold: {cfg.get('MAX_HOLDING_HOURS', 'N/A')}h")
        print(f"Last Engine Activity: {last_log_time}")
        print(f"Stats: Wins={stats.get('total_wins', 0)}, Losses={stats.get('total_losses', 0)}, WinRate={stats.get('win_rate', 0.0):.1f}%, PnL=${stats.get('total_pnl', 0.0):.2f}")
        
        # Position matching
        print(f"Local Positions: {list(local_positions.keys())}")
        if local_positions:
            for sym, pos_data in local_positions.items():
                claimed_positions[sym] = b
                entry_time = pos_data.get("entry_time") or pos_data.get("timestamp") or "N/A"
                entry_price = float(pos_data.get("entry_price") or 0.0)
                amount = float(pos_data.get("amount") or 0.0)
                side = pos_data.get("side") or pos_data.get("direction")
                tp = pos_data.get("take_profit") or pos_data.get("tp_price")
                sl = pos_data.get("stop_loss") or pos_data.get("sl_price")
                
                # Check match with exchange
                ex_p = ex_positions.get(sym)
                if ex_p:
                    match_side = (ex_p["side"].lower() == str(side).lower())
                    match_amt = abs(abs(ex_p["contracts"]) - abs(amount)) < 1e-4
                    print(f"  [HOLDING] {sym}: {side} {amount} @ ${entry_price:.4f} | EntryTime: {entry_time}")
                    print(f"    Exchange Match: SideOK={match_side}, AmtOK={match_amt} (ExAmt={ex_p['contracts']}) | Mark: ${ex_p['markPrice']:.4f} | uPnL: ${ex_p['unrealizedPnl']:+.4f}")
                    print(f"    TP: {tp} | SL: {sl}")
                else:
                    print(f"  [GHOST WARNING] {sym}: Local records {side} {amount}, but NOT found on Exchange!")
        else:
            print(f"  [FLAT] Currently 0 open positions. (대기 중)")
            # Let's see recent scan or reason from log
            print(f"  Recent Log Tail:")
            for l in last_log_lines[-3:]:
                print(f"    {l[:120]}")

    print("\n=== [4. ORPHAN POSITIONS CHECK] ===")
    orphan_found = False
    for sym, p in ex_positions.items():
        if sym not in claimed_positions:
            print(f"  [ORPHAN WARNING] {sym} is open on Binance ({p['side']} {p['contracts']}), but NOT claimed by any bot!")
            orphan_found = True
    if not orphan_found:
        print("  All exchange positions are correctly mapped to bots. No orphans!")

asyncio.run(main())
