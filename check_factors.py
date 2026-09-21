import json
import os

bots = ["8403", "8405"]

print("=== 8403, 8405 무포지션 원인 정밀 2차 검증 ===")
for b in bots:
    print(f"\n[{b}] 상태 점검 시작:")
    state_file = f"/Users/l/project/{b}/data/state.json"
    conf_file = f"/Users/l/project/{b}/config.json"
    
    if os.path.exists(state_file):
        with open(state_file, 'r', encoding='utf-8') as f:
            st = json.load(f)
        
        switch_lock = st.get("switch_lock_desc", "")
        today_pnl = st.get("today_pnl", 0)
        daily_ret = st.get("daily_ret", 0)
        holding = st.get("holding")
        last_flat = st.get("last_flat")
        
        print(f"  - holding: {holding}")
        print(f"  - switch_lock_desc: '{switch_lock}'")
        print(f"  - today_pnl: {today_pnl}, daily_ret: {daily_ret}%")
        print(f"  - last_flat: {last_flat}")
    else:
        print(f"  - state.json 없음: {state_file}")
        
    if os.path.exists(conf_file):
        with open(conf_file, 'r', encoding='utf-8') as f:
            cf = json.load(f)
            
        auto_tr = cf.get("AUTO_TRADING")
        print(f"  - AUTO_TRADING: {auto_tr}")
    else:
        print(f"  - config.json 없음: {conf_file}")

