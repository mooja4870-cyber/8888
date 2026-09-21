import os
import json
import time

bots = ["8401", "8402", "8403", "8404", "8405", "8406", "8407", "8408", "8409", "8410"]

print("=== 봇 별 실시간 상태 점검 ===")
for b in bots:
    state_file = f"/Users/l/project/{b}/data/state.json"
    conf_file = f"/Users/l/project/{b}/data/config.json"
    
    holding = "N/A"
    poslong = 0
    posshort = 0
    err = None
    
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                st = json.load(f)
            holding = st.get("holding", False)
            poslong = st.get("ex_poslong", 0)
            posshort = st.get("ex_posshort", 0)
            err = st.get("ex_err")
            auto = st.get("config", {}).get("AUTO_TRADING", "N/A")
            print(f"[{b}] holding={holding}, Long={poslong}, Short={posshort}, Auto={auto}, Err={err}")
        except Exception as e:
            print(f"[{b}] state.json 오류: {e}")
    else:
        print(f"[{b}] state.json 없음")
        
