import json
import re

bots = ['8407', '8409', '8410']
new_whitelist = ["SOL/USDT:USDT", "ETH/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT"]
new_max_pos = 3

for bot in bots:
    # 1. Update core/config.py
    cfg_path = f'/Users/l/project/{bot}/core/config.py'
    with open(cfg_path, 'r') as f:
        content = f.read()
    
    # regex to replace SYMBOL_WHITELIST
    content = re.sub(
        r'SYMBOL_WHITELIST:\s*List\[str\]\s*=\s*field\(default_factory=lambda:\s*\[.*?\]\)', 
        f'SYMBOL_WHITELIST: List[str] = field(default_factory=lambda: {new_whitelist})', 
        content
    )
    # regex to replace MAX_POSITIONS
    content = re.sub(
        r'MAX_POSITIONS:\s*int\s*=\s*\d+', 
        f'MAX_POSITIONS: int = {new_max_pos}', 
        content
    )
    
    with open(cfg_path, 'w') as f:
        f.write(content)
        
    # 2. Update config.json
    json_path = f'/Users/l/project/{bot}/config.json'
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        data['SYMBOL_WHITELIST'] = new_whitelist
        data['MAX_POSITIONS'] = new_max_pos
        with open(json_path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Updated {bot} config.json")
    except Exception as e:
        print(f"Failed to update {json_path}: {e}")

