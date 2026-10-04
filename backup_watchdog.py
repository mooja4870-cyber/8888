import os
import time
import shutil
import logging
from datetime import datetime

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("backup_watchdog.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

BASE_DIR = "/Users/l/project"
BOTS = ["8401", "8402", "8403", "8404", "8405", "8406", "8407", "8408", "8409", "8410"]
FILES_TO_BACKUP = ["trade_history.csv", "stats.json"]

def run():
    logging.info("🚀 1분 단위 매매이력 통합 백업 워치독 가동 시작!")
    
    last_hourly_run = None
    
    while True:
        try:
            now = datetime.now()
            is_hourly_time = (now.minute == 0)
            
            # 정각 중복 방지 로직
            if is_hourly_time:
                if last_hourly_run == now.hour:
                    is_hourly_time = False 
                else:
                    last_hourly_run = now.hour
            
            for bot_id in BOTS:
                data_dir = os.path.join(BASE_DIR, bot_id, "data")
                if not os.path.exists(data_dir):
                    continue

                for filename in FILES_TO_BACKUP:
                    src_path = os.path.join(data_dir, filename)
                    if not os.path.exists(src_path):
                        continue
                        
                    # 1. Latest Backup (매 분 덮어쓰기)
                    latest_bak_path = os.path.join(data_dir, f"{filename}.latest.bak")
                    try:
                        shutil.copy2(src_path, latest_bak_path)
                    except Exception:
                        pass

                    # 2. Hourly Backup (매 정각마다 덮어쓰기, 00~23)
                    if is_hourly_time:
                        hour_str = now.strftime("%H")
                        hourly_bak_path = os.path.join(data_dir, f"{filename}.hourly_{hour_str}.bak")
                        try:
                            shutil.copy2(src_path, hourly_bak_path)
                        except Exception:
                            pass
            
            logging.info(f"✅ {len(BOTS)}개 봇 데이터 백업 1회 사이클 완료 (정각 백업: {is_hourly_time})")
            
            # 60초 대기
            time.sleep(60)
            
        except Exception as e:
            logging.error(f"워치독 루프 에러: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run()
