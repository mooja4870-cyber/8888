#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8409 봇 타임프레임 15m -> 1h 수정 패치
"""
import os
import json

BOT_DIR = "/Users/l/project/8409"

def update_config():
    path = os.path.join(BOT_DIR, "config.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    data["TIMEFRAME"] = "1h"
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("✅ 8409 config.json TIMEFRAME='1h' 수정 완료")

def update_ver():
    path = os.path.join(BOT_DIR, "ver.md")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
        
    new_entry = """## v10.2.0
Date: 2026-08-26

### 변경 내용
* 진입 타임프레임 변경: 15m (15분봉) ➡️ **1h (1시간봉)**
  - 초단기 노이즈 감소 및 추세 지속성 극대화
  - QAR-ARE Ultra 엔진의 1시간봉 기준 모멘텀/신호 정합성 적용

"""
    content = new_entry + content
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ 8409 ver.md v10.2.0 갱신 완료")

if __name__ == "__main__":
    update_config()
    update_ver()
