import subprocess
import json

bots = ["8401", "8402", "8410"]
for b in bots:
    stats_path = f"/Users/l/project/{b}/data/stats.json"
    perf_start = ""
    try:
        with open(stats_path, 'r', encoding='utf-8') as f:
            st = json.load(f)
            perf_start = st.get("perf_start_time", "")
    except:
        pass
    
    out = subprocess.check_output(
        ["python3", "/Users/l/project/8888/extract_bot_metrics.py", f"/Users/l/project/{b}", perf_start],
        stderr=subprocess.DEVNULL
    )
    res = json.loads(out.decode('utf-8').strip().split('\n')[-1])
    print(f"[{b}] from extract_bot_metrics:")
    print(f"  Since W/L: {res.get('since_w')}W/{res.get('since_l')}L (Total: {res.get('since_orders')})")
    print(f"  Seq: {res.get('seq')}")
    print(f"  순/역 20: 순{res.get('sun20')}+역{res.get('yeok20')}")
