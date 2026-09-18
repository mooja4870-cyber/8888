import os
import glob
import re

def process_file(filepath, engine_ref):
    if not os.path.exists(filepath):
        return False
        
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(r'(csv_log\(\{)')
    
    inject_str = f'\\1\n                                "trade_mode": "역방향" if getattr({engine_ref}, "USE_BLUEFROG", True) else "순방향",'
    
    if '"trade_mode":' not in content:
        new_content = pattern.sub(inject_str, content)
        if new_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            return True
    return False

patched = 0
for d in glob.glob("/Users/l/project/840*"):
    if not os.path.isdir(d): continue
    
    if process_file(os.path.join(d, "core", "engine.py"), "self.cfg"): patched += 1
    if process_file(os.path.join(d, "core", "trader.py"), "self.cfg"): patched += 1
    if process_file(os.path.join(d, "core", "pnl_reconciler.py"), "self.engine.cfg"): patched += 1

print(f"Patched {patched} files.")
