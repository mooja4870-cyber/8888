#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8888 집계 및 디스코드 알림 대상 8개 봇(8401, 8402, 8403, 8404, 8407, 8408, 8409, 8410) 일괄 반영 패치
"""
import os
import re
import json

BASE_DIR = "/Users/l/project/8888"

# 1. app.py 수정
app_path = os.path.join(BASE_DIR, "app.py")
with open(app_path, "r", encoding="utf-8") as f:
    app_text = f.read()

# BOTS 리스트 교체
new_bots = """BOTS = [
    ("8401", 8401, "OKX"),
    ("8402", 8402, "OKX"),
    ("8403", 8403, "OKX"),
    ("8404", 8404, "OKX"),
    ("8407", 8407, "BNC"),
    ("8408", 8408, "BNC"),
    ("8409", 8409, "BNC"),
    ("8410", 8410, "BNC"),
]"""
app_text = re.sub(r"BOTS\s*=\s*\[[\s\S]*?\]\n\n\ndef port_alive", new_bots + "\n\n\ndef port_alive", app_text)

# EXCLUDED_BOTS 정리
new_excluded = """EXCLUDED_BOTS = [
    ("8405", 8405, "OKX"),
]"""
app_text = re.sub(r"EXCLUDED_BOTS\s*=\s*\[[\s\S]*?\]", new_excluded, app_text)

# target_bots 리스트 업데이트
app_text = app_text.replace(
    'target_bots = ["8401", "8402", "8403", "8404", "8408", "8409"]',
    'target_bots = ["8401", "8402", "8403", "8404", "8407", "8408", "8409", "8410"]'
)

with open(app_path, "w", encoding="utf-8") as f:
    f.write(app_text)
print("✅ 8888/app.py 8개 봇 집계 설정 완료")

# 2. discord_alert.py 수정
da_path = os.path.join(BASE_DIR, "discord_alert.py")
with open(da_path, "r", encoding="utf-8") as f:
    da_text = f.read()

da_text = re.sub(
    r'group_1_names\s*=\s*\{[\s\S]*?\}',
    'group_1_names = {"8401", "8402", "8403", "8404", "8407", "8408", "8409", "8410"}',
    da_text
)
da_text = da_text.replace("통합그룹(8401,2,3,4,8,9) 전체", "8개 봇(8401~8410) 통합 전체")

with open(da_path, "w", encoding="utf-8") as f:
    f.write(da_text)
print("✅ 8888/discord_alert.py 8개 봇 알림 설정 완료")

# 3. send_discord_hourly_graph.py 수정
sdh_path = os.path.join(BASE_DIR, "send_discord_hourly_graph.py")
if os.path.exists(sdh_path):
    with open(sdh_path, "r", encoding="utf-8") as f:
        sdh_text = f.read()
    
    sdh_text = re.sub(
        r'GROUP_A_IDS\s*=\s*\[[\s\S]*?\]',
        'GROUP_A_IDS = ["8401", "8402", "8403", "8404", "8407", "8408", "8409", "8410"]',
        sdh_text
    )
    sdh_text = re.sub(
        r'ALL_BOT_IDS\s*=\s*\[[\s\S]*?\]',
        'ALL_BOT_IDS = ["8401", "8402", "8403", "8404", "8407", "8408", "8409", "8410"]',
        sdh_text
    )
    with open(sdh_path, "w", encoding="utf-8") as f:
        f.write(sdh_text)
    print("✅ 8888/send_discord_hourly_graph.py 8개 봇 설정 완료")

# 4. send_discord_stats.py 수정
sds_path = os.path.join(BASE_DIR, "send_discord_stats.py")
if os.path.exists(sds_path):
    with open(sds_path, "r", encoding="utf-8") as f:
        sds_text = f.read()
    
    new_sds_bots = """BOTS = [
    ("8401", "8401_OKX"),
    ("8402", "8402_OKX"),
    ("8403", "8403_OKX"),
    ("8404", "8404_OKX"),
    ("8407", "8407_BNC"),
    ("8408", "8408_BNC"),
    ("8409", "8409_BNC"),
    ("8410", "8410_BNC"),
]"""
    sds_text = re.sub(r'BOTS\s*=\s*\[[\s\S]*?\]', new_sds_bots, sds_text)
    with open(sds_path, "w", encoding="utf-8") as f:
        f.write(sds_text)
    print("✅ 8888/send_discord_stats.py 8개 봇 설정 완료")

# 5. discord_bot_listener.py 수정
dbl_path = os.path.join(BASE_DIR, "discord_bot_listener.py")
if os.path.exists(dbl_path):
    with open(dbl_path, "r", encoding="utf-8") as f:
        dbl_text = f.read()
    
    dbl_text = re.sub(
        r'valid_bots\s*=\s*\[[\s\S]*?\]',
        'valid_bots = ["8401", "8402", "8403", "8404", "8407", "8408", "8409", "8410"]',
        dbl_text
    )
    with open(dbl_path, "w", encoding="utf-8") as f:
        f.write(dbl_text)
    print("✅ 8888/discord_bot_listener.py 8개 봇 설정 완료")

# 6. ver.md 갱신
ver_path = os.path.join(BASE_DIR, "ver.md")
with open(ver_path, "r", encoding="utf-8") as f:
    ver_text = f.read()

new_ver_entry = """## v11.0.0
Date: 2026-08-26

### 변경 내용
* **8개 봇 통합 집계 및 디스코드 알림 대상 전면 개편**
  - 집계 및 알림 대상: **8401, 8402, 8403, 8404, 8407, 8408, 8409, 8410 (총 8개 봇)**
  - 대시보드 UI(`app.py`) 종합 실시간 집계 8개 봇 동기화
  - 디스코드 1분/5분 관제 알림(`discord_alert.py`, `send_discord_stats.py`, `send_discord_hourly_graph.py`) 전면 적용

### 수정 파일
* app.py
* discord_alert.py
* send_discord_hourly_graph.py
* send_discord_stats.py
* discord_bot_listener.py
* seeds.json

"""
ver_text = new_ver_entry + ver_text
with open(ver_path, "w", encoding="utf-8") as f:
    f.write(ver_text)
print("✅ 8888/ver.md v11.0.0 갱신 완료")
