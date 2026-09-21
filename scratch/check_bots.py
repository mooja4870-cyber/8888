import json, os, time

bots = ["8401", "8402", "8403", "8404", "8405", "8406", "8407", "8408", "8409", "8410"]
base_dir = "/Users/l/project"

print(f"{'BOT':<6} {'PROCESS':<8} {'POS':<6} {'LAST_METRIC_UPDATE':<25} {'ERRORS_IN_LOG(Last 100l)':<20}")

for b in bots:
    bot_dir = os.path.join(base_dir, b)
    if not os.path.isdir(bot_dir):
        continue
        
    # Check if process is running
    is_running = "NO"
    try:
        ps_out = os.popen(f"ps aux | grep '{b}/bot.py' | grep -v grep").read()
        if ps_out.strip():
            is_running = "YES"
    except:
        pass
        
    # check pos from metrics.json
    metrics_path = os.path.join(bot_dir, "metrics.json")
    pos = "N/A"
    last_update = "N/A"
    if os.path.exists(metrics_path):
        mtime = os.path.getmtime(metrics_path)
        last_update = time.strftime('%m-%d %H:%M:%S', time.localtime(mtime))
        try:
            with open(metrics_path, 'r') as f:
                data = json.load(f)
                pos = data.get("position", "NONE")
                # sometimes it is 0 or "LONG", "SHORT"
                if pos == 0 or str(pos) == "0.0": pos = "NONE"
        except:
            pos = "ERR"

    # check errors in log
    log_path = os.path.join(bot_dir, "bot.log")
    err_count = 0
    if os.path.exists(log_path):
        try:
            tail_out = os.popen(f"tail -n 100 {log_path}").read()
            err_count = tail_out.lower().count("error") + tail_out.lower().count("exception")
        except:
            pass

    print(f"{b:<6} {is_running:<8} {str(pos):<6} {last_update:<25} {err_count:<20}")
