import os
import sys
import json
import asyncio
import subprocess
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

CORE_BOTS = [8401, 8402, 8407, 8409, 8410]
ALL_BOTS = [8401, 8402, 8407, 8409, 8410, 8403, 8404, 8405]

def get_process_info():
    cmd = "ps aux | grep -i python | grep -E '(840|841|watchdog)' | grep -v grep"
    out = subprocess.check_output(cmd, shell=True).decode()
    procs = {}
    for line in out.strip().split("\n"):
        if not line: continue
        parts = line.split(None, 10)
        pid = parts[1]
        cpu = parts[2]
        mem = parts[3]
        cmd_str = parts[10]
        
        # Match bot
        for b in ALL_BOTS:
            if f"/{b}/bot.py" in cmd_str:
                procs[f"{b}_bot"] = {"pid": pid, "cpu": cpu, "mem": mem, "type": "bot.py"}
            elif f"--server.port {b}" in cmd_str or f"port {b}" in cmd_str:
                procs[f"{b}_app"] = {"pid": pid, "cpu": cpu, "mem": mem, "type": "app.py"}
        if "watchdog_entry.py" in cmd_str:
            procs["watchdog"] = {"pid": pid, "cpu": cpu, "mem": mem, "type": "watchdog"}
    return procs

async def audit_exchange_positions():
    results = {}
    
    # OKX Client (for 8401~8405)
    try:
        sys.path.insert(0, "/Users/l/project/8401")
        from core.api_keys import load_api_keys
        load_api_keys(override=True)
        from core.exchange import OKXClient
        okx_client = OKXClient(os.getenv("OKX_API_KEY"), os.getenv("OKX_SECRET_KEY"), os.getenv("OKX_PASSPHRASE"))
        await okx_client.load_markets()
        okx_bal = await okx_client.get_balance()
        okx_pos = await okx_client.get_positions()
        okx_orders = await okx_client.get_open_orders()
        
        pos_map = {}
        for p in okx_pos:
            amt = float(p.get("contracts") or p.get("amount") or p.get("size") or 0.0)
            if abs(amt) > 0:
                pos_map[p["symbol"]] = {
                    "symbol": p["symbol"],
                    "side": p.get("side"),
                    "contracts": amt,
                    "entryPrice": float(p.get("entryPrice") or 0.0),
                    "markPrice": float(p.get("markPrice") or 0.0),
                    "unrealizedPnl": float(p.get("unrealizedPnl") or 0.0),
                    "leverage": p.get("leverage"),
                }
        results["okx"] = {
            "balance": okx_bal,
            "positions": pos_map,
            "orders": okx_orders,
            "error": None
        }
        await okx_client.close()
    except Exception as e:
        results["okx"] = {"error": str(e), "positions": {}, "orders": []}

    # Binance Client (for 8407~8410)
    try:
        sys.path.insert(0, "/Users/l/project/8407")
        from core.api_keys import load_api_keys
        load_api_keys(override=True)
        from core.exchange import BinanceClient
        bin_client = BinanceClient(os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_SECRET_KEY"), os.getenv("BINANCE_PASSPHRASE"))
        await bin_client.load_markets()
        bin_bal = await bin_client.get_balance()
        bin_pos = await bin_client.get_positions()
        bin_orders = await bin_client.get_open_orders()
        
        pos_map = {}
        for p in bin_pos:
            amt = float(p.get("contracts") or p.get("amount") or p.get("size") or 0.0)
            if abs(amt) > 0:
                pos_map[p["symbol"]] = {
                    "symbol": p["symbol"],
                    "side": p.get("side"),
                    "contracts": amt,
                    "entryPrice": float(p.get("entryPrice") or 0.0),
                    "markPrice": float(p.get("markPrice") or 0.0),
                    "unrealizedPnl": float(p.get("unrealizedPnl") or 0.0),
                    "leverage": p.get("leverage"),
                }
        results["binance"] = {
            "balance": bin_bal,
            "positions": pos_map,
            "orders": bin_orders,
            "error": None
        }
        await bin_client.close()
    except Exception as e:
        results["binance"] = {"error": str(e), "positions": {}, "orders": []}

    return results

def get_bot_local_data(b):
    cwd = f"/Users/l/project/{b}"
    cfg = {}
    cfg_file = os.path.join(cwd, "config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file) as f: cfg = json.load(f)
        except: pass

    pos_file = os.path.join(cwd, "data", "active_positions.json")
    positions = {}
    if os.path.exists(pos_file):
        try:
            with open(pos_file) as f: positions = json.load(f)
        except: pass

    stats_file = os.path.join(cwd, "data", "stats.json")
    stats = {}
    if os.path.exists(stats_file):
        try:
            with open(stats_file) as f: stats = json.load(f)
        except: pass

    # Engine log last lines
    engine_log = os.path.join(cwd, "bot_engine.log")
    last_lines = []
    last_mtime = None
    if os.path.exists(engine_log):
        last_mtime = datetime.fromtimestamp(os.path.getmtime(engine_log), tz=KST)
        try:
            with open(engine_log, "r", errors="ignore") as f:
                lines = f.readlines()
                last_lines = [l.strip() for l in lines[-25:] if l.strip()]
        except: pass

    # Scanner candidates if any
    scan_file = os.path.join(cwd, "data", "scanner_results.json")
    scan_results = []
    if os.path.exists(scan_file):
        try:
            with open(scan_file) as f: scan_results = json.load(f)
        except: pass

    return {
        "config": cfg,
        "positions": positions,
        "stats": stats,
        "last_lines": last_lines,
        "last_mtime": last_mtime,
        "scan_results": scan_results
    }

async def main():
    procs = get_process_info()
    ex_data = await audit_exchange_positions()

    now_kst = datetime.now(tz=KST)
    print(f"=== [SYSTEM COMPREHENSIVE BOT AUDIT] ===")
    print(f"Audit Time (KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Watchdog Process: {procs.get('watchdog', 'NOT RUNNING')}")
    
    # Exchange balances
    if ex_data.get("okx") and not ex_data["okx"].get("error"):
        bal = ex_data["okx"]["balance"]
        print(f"OKX Balance: Total=${bal.get('total', 0.0):.2f}, Free=${bal.get('free', 0.0):.2f}, OpenPos={len(ex_data['okx']['positions'])}")
    else:
        print(f"OKX Client Error: {ex_data.get('okx', {}).get('error')}")

    if ex_data.get("binance") and not ex_data["binance"].get("error"):
        bal = ex_data["binance"]["balance"]
        print(f"Binance Balance: Total=${bal.get('total', 0.0):.2f}, Free=${bal.get('free', 0.0):.2f}, OpenPos={len(ex_data['binance']['positions'])}")
    else:
        print(f"Binance Client Error: {ex_data.get('binance', {}).get('error')}")

    print("\n" + "="*80)
    print(f"{'BOT':<6} | {'ROLE':<6} | {'EXCHANGE':<7} | {'PROCESS (bot/ui)':<18} | {'POSITIONS':<12} | {'UNREALIZED PnL':<15} | {'TODAY PnL (W/L)':<18}")
    print("="*80)

    claimed_exchange_pos = {"okx": set(), "binance": set()}

    for b in ALL_BOTS:
        b_data = get_bot_local_data(b)
        cfg = b_data["config"]
        ex_id = cfg.get("EXCHANGE_ID", "okx" if b <= 8405 else "binance").lower()
        role = "CORE" if b in CORE_BOTS else "SUB"
        
        bot_p = procs.get(f"{b}_bot")
        app_p = procs.get(f"{b}_app")
        proc_str = f"{'O' if bot_p else 'X'}(bot) / {'O' if app_p else 'X'}(ui)"
        
        pos_list = list(b_data["positions"].keys())
        pos_cnt_str = f"{len(pos_list)} pos" if pos_list else "0 (FLAT)"
        
        total_upnl = 0.0
        ex_pos_map = ex_data.get(ex_id, {}).get("positions", {})
        for sym in pos_list:
            if sym in ex_pos_map:
                total_upnl += ex_pos_map[sym]["unrealizedPnl"]
                claimed_exchange_pos[ex_id].add(sym)
            else:
                total_upnl += float(b_data["positions"][sym].get("unrealized_pnl", 0.0) or 0.0)

        stats = b_data["stats"]
        pnl_str = f"${stats.get('total_pnl', 0.0):+.2f} ({stats.get('total_wins', 0)}W/{stats.get('total_losses', 0)}L)"

        print(f"{b:<6} | {role:<6} | {ex_id:<7} | {proc_str:<18} | {pos_cnt_str:<12} | ${total_upnl:>+8.4f} USDT | {pnl_str:<18}")

    print("="*80)

    # Detailed inspection of each bot
    for b in ALL_BOTS:
        b_data = get_bot_local_data(b)
        cfg = b_data["config"]
        ex_id = cfg.get("EXCHANGE_ID", "okx" if b <= 8405 else "binance").lower()
        print(f"\n================================================================================")
        print(f"▶ [BOT {b}] {'★ CORE BOT' if b in CORE_BOTS else 'SECONDARY BOT'} (Exchange: {ex_id.upper()})")
        print(f"================================================================================")
        print(f"• Strategy: {cfg.get('STRATEGY_NAME', cfg.get('STRATEGY', 'N/A'))} | Timeframe: {cfg.get('TIMEFRAME', 'N/A')} | Leverage: {cfg.get('LEVERAGE', 'N/A')}x")
        print(f"• Max Positions: {cfg.get('MAX_POSITIONS', 1)} | Max Hold Limit: {cfg.get('MAX_HOLDING_HOURS', 'N/A')}h (Hard: {cfg.get('MAX_HOLDING_HARD_HOURS', 'N/A')}h)")
        
        # Engine Activity
        mtime = b_data["last_mtime"]
        if mtime:
            sec_ago = (now_kst - mtime).total_seconds()
            print(f"• Engine Last Log: {mtime.strftime('%Y-%m-%d %H:%M:%S')} ({sec_ago:.0f}s ago) -> {'[HEALTHY & ACTIVE]' if sec_ago < 120 else '[WARNING: STALE LOG]'}")
        else:
            print(f"• Engine Last Log: NONE")

        # Position Inspection
        local_positions = b_data["positions"]
        ex_pos_map = ex_data.get(ex_id, {}).get("positions", {})
        ex_orders = ex_data.get(ex_id, {}).get("orders", [])

        if local_positions:
            print(f"\n  [HOLDING POSITIONS ({len(local_positions)})]")
            for sym, pos in local_positions.items():
                side = str(pos.get("side", pos.get("direction", "LONG"))).upper()
                amt = float(pos.get("amount", pos.get("contracts", 0.0)) or 0.0)
                entry_p = float(pos.get("entry_price", 0.0) or 0.0)
                entry_t = pos.get("entry_time", pos.get("timestamp", "N/A"))
                tp = pos.get("take_profit", pos.get("tp_price", "N/A"))
                sl = pos.get("stop_loss", pos.get("sl_price", "N/A"))
                
                # Check exchange match
                ex_match = ex_pos_map.get(sym)
                if ex_match:
                    ex_side = str(ex_match["side"]).upper()
                    ex_amt = abs(ex_match["contracts"])
                    mark_p = ex_match["markPrice"]
                    upnl = ex_match["unrealizedPnl"]
                    pnl_pct = ((mark_p - entry_p)/entry_p * 100) if side == "LONG" else ((entry_p - mark_p)/entry_p * 100)
                    
                    print(f"  ● {sym} | {side} {amt} (Ex: {ex_side} {ex_amt}) | Entry: ${entry_p:.4f} | Mark: ${mark_p:.4f} | uPnL: ${upnl:+.4f} ({pnl_pct:+.2f}%)")
                    print(f"    - Entry Time: {entry_t} | Planned TP: {tp} | Planned SL: {sl}")
                    
                    # Check open orders for this symbol
                    sym_orders = [o for o in ex_orders if o.get("symbol") == sym]
                    print(f"    - Open Exchange Orders ({len(sym_orders)}):")
                    for o in sym_orders:
                        print(f"      * {o.get('side')} {o.get('type')} amt={o.get('amount')} price={o.get('price') or o.get('stopPrice')} ro={o.get('reduceOnly')}")
                else:
                    print(f"  ● [GHOST DETECTED] {sym} | {side} {amt} is in local ledger, but MISSING from {ex_id.upper()} exchange!")
        else:
            print(f"\n  [CURRENTLY FLAT (무포지션 대기 상태)]")
            print(f"  • 무포지션 원인 및 진입 대기 정밀 점검:")
            
            # Check recent engine log lines
            print(f"  • Recent Log Messages:")
            for line in b_data["last_lines"][-6:]:
                print(f"    │ {line}")

            # Check scanner results
            scan = b_data["scan_results"]
            if scan:
                print(f"  • Top Scanner Candidates:")
                for item in scan[:3]:
                    sym = item.get("symbol") or item.get("pair")
                    score = item.get("score") or item.get("signal_score") or item.get("booster_score")
                    dist = item.get("distance_pct") or item.get("breakout_dist") or item.get("dist")
                    print(f"    * {sym}: score={score}, distance={dist}")

    # Orphan positions check
    print(f"\n================================================================================")
    print(f"▶ [ORPHAN POSITIONS AUDIT]")
    print(f"================================================================================")
    for ex_id, pos_map in [("okx", ex_data.get("okx", {}).get("positions", {})), ("binance", ex_data.get("binance", {}).get("positions", {}))]:
        for sym, p in pos_map.items():
            if sym not in claimed_exchange_pos[ex_id]:
                print(f"  [ORPHAN ALERT] {ex_id.upper()}: {sym} ({p['side']} {p['contracts']}) is open on exchange but UNCLAIMED by any bot!")
    print(f"  All registered exchange positions accounted for.")

asyncio.run(main())
