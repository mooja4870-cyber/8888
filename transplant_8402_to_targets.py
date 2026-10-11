#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transplant_8402_to_targets.py — 8402 [QVT 눌림목 스나이퍼]를 8401, 8407, 8409로 완전 이식
"""
import os
import shutil
import json
import re
import subprocess
import py_compile
from datetime import datetime

SRC_DIR = "/Users/l/project/8402"
TARGETS = {
    "8401": {"exchange": "okx", "port": 8401, "title": "8401 [QVT 눌림목 스나이퍼 (1h)]"},
    "8407": {"exchange": "binance", "port": 8407, "title": "8407 [QVT 눌림목 스나이퍼 (1h)]"},
    "8409": {"exchange": "binance", "port": 8409, "title": "8409 [QVT 눌림목 스나이퍼 (1h)]"},
}

def transplant():
    print("=== [8402 -> 8401, 8407, 8409] 봇 이식 수술 시작 ===")
    
    for bot_id, info in TARGETS.items():
        dst_dir = f"/Users/l/project/{bot_id}"
        print(f"\n>>> [{bot_id}] 이식 수술 집도 중...")
        
        # 1. 8401 실행 중인 프로세스 종료 (8407, 8409는 이미 .stopped 상태)
        if bot_id == "8401":
            print(f"[{bot_id}] 기존 실행 프로세스 안전 종료 중...")
            try:
                out = subprocess.check_output(["ps", "aux"]).decode("utf-8")
                for line in out.splitlines():
                    if f"/project/{bot_id}" in line and ("bot.py" in line or "streamlit" in line):
                        pid = line.split()[1]
                        os.system(f"kill -9 {pid} 2>/dev/null")
                        print(f"[{bot_id}] Killed process PID {pid}")
            except Exception as e:
                print(f"[{bot_id}] Process kill error: {e}")

        # 2. 타겟 봇의 기존 뇌와 껍데기 완전 삭제 (자아 파일 .env, api.md 등은 보존)
        dst_core = os.path.join(dst_dir, "core")
        if os.path.exists(dst_core):
            shutil.rmtree(dst_core)
            print(f"[{bot_id}] 기존 core/ 완전 삭제 완료")

        for f_name in ["config.json", "app.py", "bot.py"]:
            f_path = os.path.join(dst_dir, f_name)
            if os.path.exists(f_path):
                os.remove(f_path)
                print(f"[{bot_id}] 기존 {f_name} 완전 삭제 완료")

        # 3. 소스 봇(8402)의 뇌와 껍데기 이식 복사
        # 3-1. core 디렉토리 복사
        shutil.copytree(os.path.join(SRC_DIR, "core"), dst_core)
        print(f"[{bot_id}] 8402 core/ 이식 복사 완료")

        # 3-2. bot.py 복사
        shutil.copy2(os.path.join(SRC_DIR, "bot.py"), os.path.join(dst_dir, "bot.py"))
        print(f"[{bot_id}] 8402 bot.py 이식 복사 완료")

        # 3-3. app.py 복사 및 포트/타이틀 자아 적응
        with open(os.path.join(SRC_DIR, "app.py"), "r", encoding="utf-8") as f:
            app_code = f.read()

        # 포트 번호 치환
        app_code = app_code.replace("--server.port 8402", f"--server.port {info['port']}")
        app_code = app_code.replace("8402", bot_id)
        # 사이드바 타이틀 치환
        app_code = re.sub(
            r'f\'<span style="color:#ffffff; font-size: 100%;">.*?</span>',
            f'f\'<span style="color:#ffffff; font-size: 100%;">{info["title"]}</span>',
            app_code
        )
        with open(os.path.join(dst_dir, "app.py"), "w", encoding="utf-8") as f:
            f.write(app_code)
        print(f"[{bot_id}] 8402 app.py 이식 및 사이드바 타이틀({info['title']}) 적용 완료")

        # 3-4. config.json 복사 및 거래소 자아 적응
        with open(os.path.join(SRC_DIR, "config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)

        cfg["EXCHANGE_ID"] = info["exchange"]
        cfg["DASHBOARD_META"] = {
            "strategy": f"QVT 눌림목 스나이퍼 (1h)",
            "indicators": "Kaufman KER, 4h EMA50/200, RSI Pullback, 1:3 RR",
            "auto_switch": False
        }
        with open(os.path.join(dst_dir, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        print(f"[{bot_id}] config.json 이식 완료 (EXCHANGE_ID={info['exchange']})")

        # 3-5. stats.json 리셋
        stats_path = os.path.join(dst_dir, "data/stats.json")
        if os.path.exists(stats_path):
            try:
                with open(stats_path, "r", encoding="utf-8") as f:
                    st = json.load(f)
                st["perf_start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st["total_trades"] = 0
                st["total_wins"] = 0
                st["total_losses"] = 0
                st["total_pnl_usdt"] = 0.0
                st["orders_today"] = 0
                st["daily_pnl_usdt"] = 0.0
                with open(stats_path, "w", encoding="utf-8") as f:
                    json.dump(st, f, indent=2, ensure_ascii=False)
                print(f"[{bot_id}] stats.json 벤치마크 기준선 갱신 완료")
            except Exception as e:
                print(f"[{bot_id}] stats.json warning: {e}")

        # 4. 핵심 실행 파일 문법 검증
        py_compile.compile(os.path.join(dst_dir, "bot.py"), doraise=True)
        py_compile.compile(os.path.join(dst_dir, "app.py"), doraise=True)
        for cf in os.listdir(dst_core):
            if cf.endswith(".py"):
                py_compile.compile(os.path.join(dst_core, cf), doraise=True)

        print(f"[{bot_id}] 핵심 파일 구문 컴파일(py_compile) 100% 정상 통과!")

        # 5. ver.md 업데이트
        ver_path = os.path.join(dst_dir, "ver.md")
        now_date = datetime.now().strftime("%Y-%m-%d")
        ver_entry = f"""# Version History

## v2.0.0
Date: {now_date}

### 변경 내용
* [Transplant] 8402 봇의 QVT 눌림목 스나이퍼 전략(v2.0.0) 완전 이식 완료
* 기존 뇌와 껍데기 완전 삭제 후 8402 코어 엔진 및 설정 이식
* 거래소 자아({info['exchange']}) 및 포트({info['port']}) 100% 보존
* 4h EMA 추세 게이트 + 1h RSI 눌림목 & 지지반등 스나이퍼 탑재
* 손익비 1:3.0 (SL 1.5% / TP 4.5% / BE 2.0%) 및 2개 슬롯 압축

### 수정 파일
* core/
* config.json
* app.py
* bot.py
* data/stats.json

### 비고
* 보스 이중 승인 획득 후 안전 이식 완료

"""
        if os.path.exists(ver_path):
            with open(ver_path, "r", encoding="utf-8") as f:
                old_ver = f.read()
            if "## v2.0.0" not in old_ver:
                with open(ver_path, "w", encoding="utf-8") as f:
                    f.write(ver_entry + "\n" + old_ver.replace("# Version History\n", ""))
        else:
            with open(ver_path, "w", encoding="utf-8") as f:
                f.write(ver_entry)
        print(f"[{bot_id}] ver.md v2.0.0 업데이트 완료")

    print("\n=== [8401, 8407, 8409] 전원 이식 완료 ===")

if __name__ == "__main__":
    transplant()
