import time
import json
import os
import subprocess

def has_positions(bot_dir):
    try:
        with open(os.path.join(bot_dir, 'data', 'active_positions.json'), 'r', encoding='utf-8') as f:
            data = json.load(f)
            return len(data) > 0
    except Exception:
        return False

def update_config_to_1h(bot_dir):
    config_path = os.path.join(bot_dir, 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if config.get("TIMEFRAME") != "1h":
            config["TIMEFRAME"] = "1h"
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            return True
    except Exception as e:
        print(f"Failed to update config for {bot_dir}: {e}")
    return False

def restart_bot(bot_dir):
    try:
        subprocess.run(f'pkill -f "{bot_dir}/bot.py"', shell=True)
        time.sleep(2)
        subprocess.run('./run.sh', shell=True, cwd=bot_dir)
        print(f"Restarted bot at {bot_dir}")
    except Exception as e:
        print(f"Failed to restart {bot_dir}: {e}")

def main():
    print("12-hour monitor started. Will sleep for 43200 seconds.")
    # Sleep for 12 hours
    time.sleep(12 * 3600)
    
    print("12 hours passed. Checking positions...")
    bots = ['/Users/l/project/8408', '/Users/l/project/8410']
    
    for bot in bots:
        if not has_positions(bot):
            print(f"No positions found in {bot}. Changing to 1h...")
            if update_config_to_1h(bot):
                restart_bot(bot)
                # ver.md 업데이트
                ver_file = os.path.join(bot, "ver.md")
                if os.path.exists(ver_file):
                    import datetime
                    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
                    with open(ver_file, "r") as f:
                        old_ver = f.read()
                    
                    new_entry = f"## v_auto_1h\nDate: {date_str}\n\n### 변경 내용\n* 12시간 무포지션 감지 자동 트리거: TIMEFRAME 1h로 하향\n\n"
                    with open(ver_file, "w") as f:
                        f.write("# Version History\n\n" + new_entry + old_ver.replace("# Version History\n\n", ""))
        else:
            print(f"Positions found in {bot}. Leaving config as is.")

if __name__ == '__main__':
    main()
