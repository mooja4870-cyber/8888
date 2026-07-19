import app
import json

data = app.collect()

for b in data.get("bots", []):
    name = b.get("name")
    if name in ["8402", "8403", "8405", "8407", "8408", "8409"]:
        print(f"\n[{name}]")
        print(f"  ex_ok: {b.get('ex_ok')}")
        print(f"  ex_error: {b.get('ex_error')}")
        print(f"  ex_balance: {b.get('ex_balance')}")
        print(f"  total (from data file): {b.get('total')}")
        print(f"  daily_ret: {b.get('daily_ret')}")
