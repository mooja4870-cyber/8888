import os
import subprocess

def list_bot_pids(bot_dir):
    try:
        output = subprocess.check_output(['pgrep', '-f', 'bot.py']).decode().strip().split('\n')
        for pid in output:
            if not pid: continue
            try:
                cmd = subprocess.check_output(['ps', '-p', pid, '-o', 'args=']).decode().strip()
                if bot_dir in cmd and "python" in cmd.lower():
                    return pid
            except:
                pass
    except:
        pass
    return None

for b in [8401, 8402, 8403, 8404, 8405, 8408, 8410]:
    bot_dir = f"/Users/l/project/{b}"
    pid = list_bot_pids(str(b))
    if pid:
        with open(f"{bot_dir}/bot.pid", "w") as f:
            f.write(pid)
        print(f"[{b}] Synced PID: {pid}")
    else:
        print(f"[{b}] Bot not running!")
