import os
import json
import re

bots = ["8404", "8405", "8406", "8409"]
for b in bots:
    print(f"\n{'='*40}\nChecking Bot {b}\n{'='*40}")
    bot_dir = f"/Users/l/project/{b}"
    
    # Check config
    config_path = f"{bot_dir}/config.json"
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            cfg = json.load(f)
            print(f"Config: LEV={cfg.get('LEVERAGE')}, MAX_POS={cfg.get('MAX_POSITIONS', cfg.get('MAX_CONCURRENT_POSITIONS'))}")
            # check API keys loosely
            keys = ["API_KEY", "SECRET_KEY", "PASSPHRASE"]
            has_keys = all(cfg.get(k) for k in keys if k in cfg or "PASSPHRASE" in k) # Binance might not have passphrase
            if not cfg.get("PASSPHRASE") and "binance" not in cfg.get("EXCHANGE", "").lower() and "binance" not in bot_dir.lower():
                has_keys = bool(cfg.get("API_KEY") and cfg.get("SECRET_KEY"))
            print(f"API Keys Configured: {has_keys}")
    else:
        print("Config: NOT FOUND")

    # Check state
    state_path = f"{bot_dir}/data/state.json"
    if os.path.exists(state_path):
        with open(state_path, 'r') as f:
            state = json.load(f)
            print(f"State: holding={state.get('holding')}, positions={len(state.get('positions', []))}")
    else:
        print("State: NOT FOUND")

    # Check logs for errors
    log_files = [f"{bot_dir}/bot_engine.log", f"{bot_dir}/bot.log", f"{bot_dir}/bot_stdout.log"]
    found_log = False
    for lf in log_files:
        if os.path.exists(lf):
            found_log = True
            try:
                with open(lf, 'rb') as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - 100000))
                    content = f.read().decode('utf-8', errors='ignore')
                    
                    errors = re.findall(r'(?i)(error|exception|fail|insufficient|timeout|reject).*', content)
                    errors = [e for e in errors if "Unclosed connector" not in e and "Event loop" not in e]
                    
                    orders = re.findall(r'(?i)(order|entry|position).*', content)
                    print(f"Log ({os.path.basename(lf)}): {len(errors)} potential errors in last 100KB")
                    if errors:
                        print(f"Sample error: {errors[-1]}")
            except Exception as e:
                print(f"Error reading {lf}: {e}")
    if not found_log:
        print("Logs: NONE FOUND")
