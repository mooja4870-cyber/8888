import json, os, subprocess

bots = ['8402', '8404']
for b in bots:
    print(f"=== [Bot {b}] Status ===")
    config_path = f"/Users/l/project/{b}/config.json"
    state_path = f"/Users/l/project/{b}/app_state.json"
    log_path = f"/Users/l/project/{b}/bot_engine.log"
    
    # 1. Config Check
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
            print(f"Config: ALLOW_LONG={cfg.get('ALLOW_LONG')}, ALLOW_SHORT={cfg.get('ALLOW_SHORT')}, AUTO_TRADING={cfg.get('AUTO_TRADING')}, MAX_POSITIONS={cfg.get('MAX_POSITIONS')}")
            
    # 2. State Check
    if os.path.exists(state_path):
        with open(state_path) as f:
            st = json.load(f)
            positions = st.get('positions', [])
            print(f"Active Positions: {len(positions)}")
            for p in positions:
                print(f"  - {p.get('symbol')} ({p.get('side')}) @ {p.get('entry_price')}")
                
    # 3. Log Check (Recent Scan/Entry attempts)
    print("Recent Engine Logs (Last 10 lines):")
    try:
        out = subprocess.check_output(f"tail -n 15 {log_path}", shell=True, text=True)
        print(out.strip())
    except:
        print("Log read failed.")
    print("\n")
