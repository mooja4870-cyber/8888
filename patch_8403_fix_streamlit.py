#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8403 (및 8402) 봇 StreamlitValueAboveMaxError 원천 해결 패치 스크립트
"""
import os
import json

def fix_config(bot_id, tp_val=0.025, sl_val=0.012):
    cfg_path = f"/Users/l/project/{bot_id}/config.json"
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["TAKE_PROFIT_PCT"] = tp_val
        data["STOP_LOSS_PCT"] = sl_val
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ {bot_id} config.json TAKE_PROFIT_PCT {tp_val} ({tp_val*100}%) 정상화 완료")

def fix_app(bot_id):
    app_path = f"/Users/l/project/{bot_id}/app.py"
    if os.path.exists(app_path):
        try:
            with open(app_path, "r", encoding="utf-8") as f:
                code = f.read()
            target = 'st.number_input("🎯 고정 익절 (%)", 0.1, 20.0,'
            replacement = 'st.number_input("🎯 고정 익절 (%)", 0.1, 100.0,'
            if target in code:
                code = code.replace(target, replacement)
                with open(app_path, "w", encoding="utf-8") as f:
                    f.write(code)
                print(f"✅ {bot_id} app.py number_input max_value 100% 확장 완료")
            else:
                print(f"ℹ️ {bot_id} app.py 타겟 패턴 미발견 또는 이미 수정됨")
        except Exception as e:
            print(f"⚠️ {bot_id} app.py 수정 중 예외 (잠금 상태일 수 있음): {e}")

if __name__ == "__main__":
    fix_config("8403", 0.025, 0.012)
    fix_app("8403")
    fix_config("8402", 0.025, 0.007)
    fix_app("8402")
