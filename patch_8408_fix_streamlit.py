#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8408 봇 StreamlitValueAboveMaxError 원천 해결 패치 스크립트
"""
import os
import json

BOT_DIR = "/Users/l/project/8408"

def fix_8408_config():
    cfg_path = os.path.join(BOT_DIR, "config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 50% -> 2.5% 정상화
    data["TAKE_PROFIT_PCT"] = 0.025
    data["STOP_LOSS_PCT"] = 0.012

    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("✅ 8408 config.json TAKE_PROFIT_PCT 0.025 정상화 완료")

def fix_8408_app():
    app_path = os.path.join(BOT_DIR, "app.py")
    with open(app_path, "r", encoding="utf-8") as f:
        code = f.read()

    # number_input max_value 확장 (20.0 -> 100.0)
    target = 'st.number_input("🎯 고정 익절 (%)", 0.1, 20.0, float(CFG.TAKE_PROFIT_PCT * 100), step=0.1, key="sb_tp",'
    replacement = 'st.number_input("🎯 고정 익절 (%)", 0.1, 100.0, float(CFG.TAKE_PROFIT_PCT * 100), step=0.1, key="sb_tp",'
    if target in code:
        code = code.replace(target, replacement)

    target_main = 'st.number_input("🎯 고정 익절 (%)", 0.1, 20.0,'
    replacement_main = 'st.number_input("🎯 고정 익절 (%)", 0.1, 100.0,'
    if target_main in code:
        code = code.replace(target_main, replacement_main)

    with open(app_path, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ 8408 app.py number_input max_value 100% 확장 완료")

if __name__ == "__main__":
    fix_8408_config()
    fix_8408_app()
