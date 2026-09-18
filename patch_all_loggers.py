import os
import glob

old_str = """        mode_val = data.get("trade_mode", data.get("mode", ""))
        if not mode_val:
            from core.config import CFG
            mode_val = "역방향" if getattr(CFG, "USE_BLUEFROG", True) else "순방향\"\"\""""
old_str = old_str[:-3]

new_str = """        mode_val = data.get("trade_mode", data.get("mode", ""))
        if not mode_val:
            import json, os
            try:
                cpath = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
                with open(cpath, "r", encoding="utf-8") as cf:
                    mode_val = "역방향" if json.load(cf).get("USE_BLUEFROG", True) else "순방향"
            except Exception:
                from core.config import CFG
                mode_val = "역방향" if getattr(CFG, "USE_BLUEFROG", True) else "순방향\"\"\""""
new_str = new_str[:-3]

patched_count = 0
for d in glob.glob("/Users/l/project/840*"):
    target = os.path.join(d, "core", "logger.py")
    if not os.path.exists(target):
        continue
        
    with open(target, "r", encoding="utf-8") as f:
        content = f.read()
        
    if old_str in content:
        content = content.replace(old_str, new_str)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Patched {target}")
        patched_count += 1
    elif new_str in content:
        print(f"Already patched {target}")

print(f"Total patched: {patched_count}")
