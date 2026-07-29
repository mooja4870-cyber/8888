import os
import sys

bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
for b in bots:
    app_path = f"/Users/l/project/{b}/app.py"
    golden_path = f"/Users/l/project/{b}/.golden/app.py"
    if not os.path.exists(app_path):
        continue
        
    with open(app_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    if "UI Config Sync Patch" in content:
        continue

    # Find the end of init_session()
    # Or just inject it at the beginning of init_session()
    target_str = "def init_session():"
    
    sync_code = """def init_session():
    # --- [UI Config Sync Patch] 실시간 설정 파일 동기화 ---
    try:
        from core.config import load_config, CFG
        new_cfg = load_config()
        # CFG 전역 인스턴스 덮어쓰기 (레퍼런스 유지)
        for k, v in new_cfg.__dict__.items():
            setattr(CFG, k, v)
        # 엔진 내부 cfg 객체 갱신
        engine = QuantumEngine.get_instance()
        engine.cfg = new_cfg
    except Exception as e:
        pass
    # ----------------------------------------------------"""
    
    new_content = content.replace(target_str, sync_code)
    
    with open(app_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    if os.path.exists(golden_path):
        with open(golden_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
    print(f"Patched {b}")
