import json, os, subprocess

def fix_bot(b):
    subprocess.run(f"pkill -f 'bot.py' && pkill -f 'streamlit' ; sleep 1", shell=True, cwd=f"/Users/l/project/{b}")
    state_file = f"/Users/l/project/{b}/data/switch_state.json"
    cfg_file = f"/Users/l/project/{b}/config.json"
    
    # Run audit logic to find truth
    with open(f"/Users/l/project/8888/hard_fix_all.py", "r") as f:
        code = f.read()
    
    # We will just reuse hard_fix_all.py logic but we will do it for ALL bots again while streamlits are dead
