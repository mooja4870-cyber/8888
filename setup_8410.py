#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8410 봇 초기 설정 및 포트 8410 바인딩 스크립트
"""
import os
import json
import re

BOT_DIR = "/Users/l/project/8410"

# 1. run.sh 수정
run_sh_path = os.path.join(BOT_DIR, "run.sh")
with open(run_sh_path, "r", encoding="utf-8") as f:
    content = f.read()

content = re.sub(r'PORT=8409', 'PORT=8410', content)
content = re.sub(r'APP_DIR="/Users/l/project/8409"', 'APP_DIR="/Users/l/project/8410"', content)
content = re.sub(r'/tmp/8409_bot\.pid', '/tmp/8410_bot.pid', content)
content = re.sub(r'/tmp/8409_ui\.pid', '/tmp/8410_ui.pid', content)
content = content.replace("8409_binance", "8410_binance")

with open(run_sh_path, "w", encoding="utf-8") as f:
    f.write(content)
print("✅ 8410 run.sh 포트(8410) 및 경로 수정 완료")

# 2. app.py 수정
app_py_path = os.path.join(BOT_DIR, "app.py")
with open(app_py_path, "r", encoding="utf-8") as f:
    app_content = f.read()

app_content = app_content.replace("8409_", "8410_").replace("8409 봇", "8410 봇")
with open(app_py_path, "w", encoding="utf-8") as f:
    f.write(app_content)
print("✅ 8410 app.py 명칭 수정 완료")

# 3. bot.py 수정
bot_py_path = os.path.join(BOT_DIR, "bot.py")
with open(bot_py_path, "r", encoding="utf-8") as f:
    bot_content = f.read()

bot_content = bot_content.replace("8409_binance", "8410_binance").replace("8408_binance", "8410_binance")
with open(bot_py_path, "w", encoding="utf-8") as f:
    f.write(bot_content)
print("✅ 8410 bot.py 명칭 수정 완료")

# 4. ver.md 생성/초기화
ver_md_path = os.path.join(BOT_DIR, "ver.md")
ver_content = """# Version History

## v1.0.0
Date: 2026-08-26

### 변경 내용
* **8410 바이낸스 봇 신규 론칭 (포트 8410)**
  - 8409 봇 기반 최첨단 QAR-ARE Ultra 퀀트 알파 엔진 이식
  - 1시간봉(1h) 기준 롱/숏 양방향 진입 체계 가동
  - Marcos López de Prado 분수차분 + Triple Barrier + Kaufman KER 휩쏘 차단

### 수정 파일
* config.json
* run.sh
* app.py
* bot.py
"""
with open(ver_md_path, "w", encoding="utf-8") as f:
    f.write(ver_content)
print("✅ 8410 ver.md 초기화 완료")

# 5. trade_history.csv 초기화
data_dir = os.path.join(BOT_DIR, "data")
os.makedirs(data_dir, exist_ok=True)
th_path = os.path.join(data_dir, "trade_history.csv")
header = "시간,심볼,유형,방향,가격,수량,수익(USDT),수익률(%),청산유형,레버리지,주문ID,체결ID,수수료(USDT),매매모드\n"
with open(th_path, "w", encoding="utf-8") as f:
    f.write(header)
print("✅ 8410 trade_history.csv 신규 생성 완료")

# 6. seeds.json에 8410 등록
seeds_path = "/Users/l/project/8888/seeds.json"
if os.path.exists(seeds_path):
    with open(seeds_path, "r", encoding="utf-8") as f:
        seeds = json.load(f)
    seeds["8410"] = {
        "seed": 10.0,
        "perf_start": "2026-08-26 23:00:00"
    }
    with open(seeds_path, "w", encoding="utf-8") as f:
        json.dump(seeds, f, ensure_ascii=False, indent=2)
    print("✅ 8888 seeds.json 8410 등록 완료")
