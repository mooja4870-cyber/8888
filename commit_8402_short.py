#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8402 ver.md 갱신 및 Git 작업 스크립트
"""
import subprocess
import os

BOT_DIR = "/Users/l/project/8402"
VER = "v9.10.0"
DATE = "2026-08-23"

entry = f"""# Version History

## {VER}

Date: {DATE}

### 변경 내용
* 세력흔적 전략(Sniper15)에 숏(Short) 포지션 진입 기능 추가
  - 15분봉 기준 신호수식 5조건(S1~S5: 신저가 하향 이탈, 첫 이탈, 음봉, 거래량 폭증, 중심값 하회) 및 세력라인·마지노선 동시 하향 이탈 시 숏 진입 로직 대칭 구현
  - 숏 손절가(마지노선) 및 1차 익절가(-5%) 산출 로직 적용
  - `config.json` 및 `core/config.py`: `ALLOW_SHORT: True` 설정으로 양방향(Long/Short) 자율 매매 활성화

### 수정 파일
* config.json
* core/config.py
* core/strategy.py
* ver.md

### 비고
* 롱/숏 대칭 신호 단위 테스트 및 실매매 엔진(bot.py + app.py) 재기동 3중 검증 완료

"""

ver_path = os.path.join(BOT_DIR, "ver.md")
with open(ver_path, "r", encoding="utf-8") as f:
    old_content = f.read()

# 기존 # Version History 제거 후 최신 내용 추가
if "# Version History" in old_content:
    old_content = old_content.replace("# Version History", "").strip()

new_content = entry + "\n" + old_content

with open(ver_path, "w", encoding="utf-8") as f:
    f.write(new_content)

print("✅ 8402 ver.md 갱신 완료")

# Git add, commit, tag, push
cmds = [
    ["git", "add", "config.json", "core/config.py", "core/strategy.py", "core/trader.py", "core/trailing_stop_manager.py", "ver.md"],
    ["git", "commit", "-m", f"feat: 세력흔적 전략 숏(Short) 포지션 진입 기능 추가 ({VER})"],
    ["git", "tag", VER],
    ["git", "push", "origin", "main"],
    ["git", "push", "origin", VER]
]

for cmd in cmds:
    res = subprocess.run(cmd, cwd=BOT_DIR, capture_output=True, text=True)
    print(f"[{' '.join(cmd)}] -> code: {res.returncode}")
    if res.stdout:
        print("  stdout:", res.stdout.strip())
    if res.stderr:
        print("  stderr:", res.stderr.strip())
