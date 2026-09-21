import os
import glob
import re

for bot_dir in glob.glob('/Users/l/project/84*'):
    if not os.path.isdir(bot_dir) or not os.path.basename(bot_dir).isdigit():
        continue
        
    alert_path = os.path.join(bot_dir, 'core', 'alert.py')
    engine_path = os.path.join(bot_dir, 'core', 'engine.py')
    
    # 1. alert.py 수정
    if os.path.exists(alert_path):
        with open(alert_path, 'r', encoding='utf-8') as f:
            alert_code = f.read()
            
        old_alert_logic = '''        if bot_folder.isdigit():
            # [8408] 본 봇은 Binance 전용. 과거 OKX 판별용 매직넘버(<=8406)는 제거.
            bot_name = f"[{bot_folder}_Binance]"'''
            
        new_alert_logic = '''        if bot_folder.isdigit():
            is_okx = "OKX" if int(bot_folder) <= 8406 else "Binance"
            bot_name = f"[{bot_folder}_{is_okx}]"'''
            
        if old_alert_logic in alert_code:
            alert_code = alert_code.replace(old_alert_logic, new_alert_logic)
            with open(alert_path, 'w', encoding='utf-8') as f:
                f.write(alert_code)
                print(f"Fixed alert.py in {bot_dir}")

    # 2. engine.py 수정
    if os.path.exists(engine_path):
        with open(engine_path, 'r', encoding='utf-8') as f:
            engine_code = f.read()
            
        bot_id = int(os.path.basename(bot_dir))
        if bot_id <= 8406:
            old_engine_msg = 'send_telegram_alert("🤖 *[AI QUANTUM]* Binance 자동매매 엔진 초기화 및 가동 성공")'
            new_engine_msg = 'send_telegram_alert("🤖 *[AI QUANTUM]* OKX 자동매매 엔진 초기화 및 가동 성공")'
            if old_engine_msg in engine_code:
                engine_code = engine_code.replace(old_engine_msg, new_engine_msg)
                with open(engine_path, 'w', encoding='utf-8') as f:
                    f.write(engine_code)
                    print(f"Fixed engine.py in {bot_dir}")
