import os
import glob

bots = glob.glob('/Users/l/project/84*')
for bot in bots:
    if "backup" in bot or not os.path.isdir(bot):
        continue
    trader_path = os.path.join(bot, 'core', 'trader.py')
    if os.path.exists(trader_path):
        with open(trader_path, 'r') as f:
            content = f.read()
        
        # Check if already patched in __init__
        init_part = content[:content.find("def ")] if "def " in content else content
        if "self._last_signal_time: Optional[datetime] = None" not in init_part:
            # Safest anchor is self.global_cooldown_until
            target = "self.global_cooldown_until: Optional[datetime] = None"
            replacement = "self.global_cooldown_until: Optional[datetime] = None\n        self._last_signal_time: Optional[datetime] = None"
            
            if target in content:
                new_content = content.replace(target, replacement)
                with open(trader_path, 'w') as f:
                    f.write(new_content)
                print(f"Patched {os.path.basename(bot)}")
            else:
                print(f"Failed to find target in {os.path.basename(bot)}")
        else:
            print(f"Already patched {os.path.basename(bot)}")
