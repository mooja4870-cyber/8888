import os
import glob

bots = glob.glob('/Users/l/project/840*') + glob.glob('/Users/l/project/8410')
for b in bots:
    bot_id = os.path.basename(b)
    lock_path = f"/tmp/quantum_{bot_id}_trader.lock"
    pid_path = os.path.join(b, "bot.pid")
    
    if os.path.exists(lock_path):
        with open(lock_path, 'r') as f:
            lock_pid = f.read().strip()
        if lock_pid:
            with open(pid_path, 'w') as f:
                f.write(lock_pid)
            print(f"[{bot_id}] Synced bot.pid to {lock_pid}")

