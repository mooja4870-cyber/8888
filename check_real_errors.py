import sys
sys.path.insert(0, '/Users/l/project/8888')
import app
import json
import os
import re

print("=== 봇 무포지션 및 에러 엄중 검증 ===")
data = app.collect()

bots = data.get("bots", [])

core_bots = ["8401", "8402", "8407", "8409", "8410"]

for b in bots:
    bid = b.get("name")
    if not bid: continue
    
    holding = b.get("holding", False)
    ex_long = b.get("ex_poslong", 0)
    ex_short = b.get("ex_posshort", 0)
    ex_err = b.get("ex_err")
    
    pos_count = ex_long + ex_short
    
    # Check mismatches
    mismatch = False
    if holding and pos_count == 0:
        mismatch = True
        print(f"🚨 [경고] {bid}: 시스템은 holding=True 이나, 실제 거래소 포지션은 0 입니다!")
    if not holding and pos_count > 0:
        mismatch = True
        print(f"🚨 [경고] {bid}: 시스템은 holding=False 이나, 거래소 포지션이 {pos_count}개 있습니다!")
        
    # Check for actual errors in state
    if ex_err:
        print(f"🚨 [경고] {bid}: 거래소 에러 상태 - {ex_err}")
        
    # check recent bot_engine.log for errors
    log_path = f"/Users/l/project/{bid}/bot_engine.log"
    err_lines = []
    if os.path.exists(log_path):
        with open(log_path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 50000))
            lines = f.read().decode('utf-8', errors='ignore').split('\n')
            
        for line in lines:
            if "Insufficient" in line or "APIError" in line or "order failed" in line.lower() or "reject" in line.lower() or "Exception:" in line:
                if "ReadTimeout" not in line and "ConnectionResetError" not in line:
                    err_lines.append(line.strip())
                    
    if err_lines:
        print(f"⚠️ [{bid}] 최근 로그 에러 발견 ({len(err_lines)}건) - 예시: {err_lines[-1]}")
        
    # Check if currently no position, might be normal but if it's a core bot
    if not holding and not mismatch and bid in core_bots:
        print(f"ℹ️ [{bid}] 현재 정상 무포지션 상태입니다. (대기 중 또는 쿨다운)")

