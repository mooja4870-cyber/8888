import sys
import subprocess

target_bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
for b in target_bots:
    bot_path = f"/Users/l/project/{b}"
    cmd = [sys.executable, "-c", "import core.engine; e=core.engine.QuantumEngine(); e.check_auto_mode_switch()"]
    res = subprocess.run(cmd, cwd=bot_path, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error in {b}: {res.stderr}")
    else:
        print(f"{b} OK")
