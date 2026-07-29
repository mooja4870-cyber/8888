import os

bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
for b in bots:
    app_path = f"/Users/l/project/{b}/app.py"
    golden_path = f"/Users/l/project/{b}/.golden/app.py"
    if not os.path.exists(app_path):
        continue
        
    with open(app_path, "r", encoding="utf-8") as f:
        content = f.read()

    # The previous patch injected "# --- [UI Config Sync Patch] 실시간 설정 파일 동기화 ---"
    # We will replace that whole block with an advanced one.
    
    start_marker = "# --- [UI Config Sync Patch] 실시간 설정 파일 동기화 ---"
    end_marker = "# ----------------------------------------------------"
    
    if start_marker in content and end_marker in content:
        head = content.split(start_marker)[0]
        tail = content.split(end_marker)[1]
        
        advanced_sync_code = """# --- [UI Config Sync Patch] 실시간 설정 파일 동기화 ---
    try:
        from core.config import load_config, CFG
        new_cfg = load_config()
        for k, v in new_cfg.__dict__.items():
            setattr(CFG, k, v)
        engine = QuantumEngine.get_instance()
        engine.cfg = new_cfg
        
        # UI Checkbox 캐시 동기화
        if "bluefrog_mode" in st.session_state:
            st.session_state.bluefrog_mode = getattr(CFG, "USE_BLUEFROG", True)
        if "auto_switch_mode" in st.session_state:
            st.session_state.auto_switch_mode = getattr(CFG, "USE_AUTO_MODE_SWITCH", True)
    except Exception as e:
        pass
    # ----------------------------------------------------"""
        
        new_content = head + advanced_sync_code + tail
        
        with open(app_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        if os.path.exists(golden_path):
            with open(golden_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        print(f"Upgraded patch on {b}")

