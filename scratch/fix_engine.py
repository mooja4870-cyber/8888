import os
import glob
import json
import subprocess

for bot_dir in glob.glob("/Users/l/project/84*"):
    engine_path = os.path.join(bot_dir, "core", "engine.py")
    if os.path.exists(engine_path):
        with open(engine_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        target = '''                        _ts = [_epoch_ms(t.get("timestamp")) for t in unlogged_exits]
                        if any(_ts):
                            _latest = max(_ts)
                            unlogged_exits = [t for t, ts in zip(unlogged_exits, _ts)
                                              if _latest - ts <= 300_000]'''
        
        replacement = '''                        _ts = [_epoch_ms(t.get("timestamp")) for t in unlogged_exits]
                        if any(_ts):
                            now_ms = time.time() * 1000
                            unlogged_exits = [t for t, ts in zip(unlogged_exits, _ts)
                                              if now_ms - ts <= 1800_000]'''
        
        if target in content:
            content = content.replace(target, replacement)
            with open(engine_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Patched {engine_path}")
        else:
            print(f"Target not found or already patched in {engine_path}")

    # Reset stats.json for 8405
    if bot_dir.endswith("8405"):
        stats_path = os.path.join(bot_dir, "data", "stats.json")
        if os.path.exists(stats_path):
            with open(stats_path, "r", encoding="utf-8") as f:
                stats = json.load(f)
            stats["daily_consec_sl"] = 0
            stats["halted_by_consec_sl"] = False
            with open(stats_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2, ensure_ascii=False)
            print(f"Reset daily_consec_sl for 8405")
