import json, os, subprocess, time

bots = ['8401', '8402', '8403', '8404', '8405', '8408', '8410']
print("=== 7 Bots Investigation ===")

for b in bots:
    log_path = f"/Users/l/project/{b}/bot_engine.log"
    print(f"\n--- [Bot {b}] ---")
    try:
        # Check for recent errors or exceptions
        errors = subprocess.check_output(f"grep -i -E 'error|exception|fail' {log_path} | tail -n 5", shell=True, text=True)
        print("Recent Errors:")
        print(errors.strip() if errors.strip() else "None")
    except:
        pass

    try:
        # Check recent signal generations
        signals = subprocess.check_output(f"grep '신호' {log_path} | tail -n 5", shell=True, text=True)
        print("Recent Signal Logs:")
        print(signals.strip())
    except:
        pass
        
    try:
        # Last status lines
        status = subprocess.check_output(f"grep '\[상태\]' {log_path} | tail -n 3", shell=True, text=True)
        print("Last Status:")
        print(status.strip())
    except:
        pass

