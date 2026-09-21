import json, os, time

bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409", "8410"]
base_dir = "/Users/l/project"

for b in bots:
    ledger_path = os.path.join(base_dir, b, "trade_ledger.json")
    if not os.path.exists(ledger_path):
        print(f"[{b}] NO LEDGER")
        continue
    try:
        with open(ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        print(f"[{b}] Ledger trades count: {len(data)}")
        if data:
            last = data[-1]
            if last.get("status") != "CLOSED":
                print(f"    -> OPEN POSITION: {last.get('direction')} entry={last.get('entry_price')} time={last.get('entry_time')}")
            else:
                print(f"    -> CLOSED. Last exit={last.get('exit_time')}")
    except Exception as e:
        print(f"[{b}] ERROR parsing ledger: {e}")

