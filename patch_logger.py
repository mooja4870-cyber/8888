import os

BOT_PORTS = ["8401", "8402", "8403", "8404", "8405", "8408", "8410"]
BASE_DIR = "/Users/l/project"

TARGET = """                    if pnl_pct >= tp_pct:
                        from core.logger import logger
                        logger.warning"""
                        
REPLACE = """                    if pnl_pct >= tp_pct:
                        logger.warning"""

for port in BOT_PORTS:
    engine_path = os.path.join(BASE_DIR, port, "core", "engine.py")
    if os.path.exists(engine_path):
        with open(engine_path, "r") as f:
            content = f.read()
        if TARGET in content:
            with open(engine_path, "w") as f:
                f.write(content.replace(TARGET, REPLACE))
            print(f"Fixed logger in {port} engine.py")
