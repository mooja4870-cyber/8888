import os

target_bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
changed_bots = []

for b in target_bots:
    paths = [
        f"/Users/l/project/{b}/.golden/core/engine.py",
        f"/Users/l/project/{b}/core/engine.py"
    ]
    
    modified = False
    for p in paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
            
            old_str = "            if len(closed_trades) < 5:\n                return"
            new_str = "            if not closed_trades:\n                return"
            
            if old_str in content:
                content = content.replace(old_str, new_str)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
                modified = True
                print(f"Patched {p}")
                
    if modified:
        changed_bots.append(b)

if changed_bots:
    with open("changed_bots_switch.txt", "w") as f:
        f.write(",".join(changed_bots))
