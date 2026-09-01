import os, sys, json, subprocess, time

def process_bot(b):
    cwd = f"/Users/l/project/{b}"
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    
    # Import inside after path changes
    import importlib
    try:
        import core.history_helper as hh
        importlib.reload(hh)
    except Exception as e:
        print(f"Import error for {b}: {e}")
        sys.path.pop(0)
        return
        
    state_file = os.path.join(cwd, "data", "switch_state.json")
    cfg_file = os.path.join(cwd, "config.json")
    
    subprocess.run("pkill -9 -f 'bot.py' || true", shell=True, cwd=cwd, stderr=subprocess.DEVNULL)
    subprocess.run("pkill -9 -f 'streamlit' || true", shell=True, cwd=cwd, stderr=subprocess.DEVNULL)
    
    try:
        raw_trades = hh.load_local_trade_history(csv_path=os.path.join(cwd, "data", "trade_history.csv"))
    except:
        sys.path.pop(0)
        return
        
    paired = hh.aggregate_and_pair_trades(raw_trades)
    closed_trades = [p for p in paired if p.get("status") == "청산 완료"]
    closed_trades.sort(key=lambda x: x.get("exit_time", ""))

    N = len(closed_trades)
    expected_mode = False
    last_switched_on_count = -1

    for n in range(1, N + 1):
        current_history = closed_trades[:n]
        if last_switched_on_count != -1 and (n - last_switched_on_count) < 3:
            continue
        should_switch = False
        if n >= 5:
            recent_5 = current_history[-5:]
            losses = sum(1 for t in recent_5 if float(t.get("pnl_usdt") or 0.0) < 0.0)
            if losses >= 3:
                should_switch = True
        elif n >= 3 and all(float(t.get("pnl_usdt") or 0.0) < 0.0 for t in current_history[-3:]):
            should_switch = True
            
        if should_switch:
            expected_mode = not expected_mode
            last_switched_on_count = n

    with open(cfg_file, "r") as f:
        cfg = json.load(f)

    if cfg.get("USE_BLUEFROG") != expected_mode:
        cfg["USE_BLUEFROG"] = expected_mode
        with open(cfg_file, "w") as f:
            json.dump(cfg, f, indent=4)
        
        if os.path.exists(state_file):
            try:
                with open(state_file, "r") as sf:
                    sdata = json.load(sf)
                sdata["last_switched_on_count"] = last_switched_on_count
                with open(state_file, "w") as sf:
                    json.dump(sdata, sf, indent=2)
            except:
                pass
        print(f"{b}: FIXED -> {expected_mode}")
    else:
        print(f"{b}: OK -> {expected_mode}")
        
    sys.path.pop(0)

for bot in [8401, 8402, 8403, 8404, 8405, 8407, 8408, 8409, 8410]:
    process_bot(bot)
