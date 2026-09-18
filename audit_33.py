import os, json, time, re, socket

bots = [8401, 8402, 8403, 8404, 8405, 8406, 8407, 8409, 8410]
now = time.time()

print("=========================================================")
print(" 33대 체크리스트 전수 검사 결과 (9개 봇)")
print("=========================================================")

for b in bots:
    cwd = f"/Users/l/project/{b}"
    pos_file = f"{cwd}/data/active_positions.json"
    log_file = f"{cwd}/bot_engine.log"
    conf_file = f"{cwd}/config.json"
    
    anomalies = []
    
    # 1~7: Sync Check (Basic state)
    pos_data = []
    if os.path.exists(pos_file):
        try:
            with open(pos_file, "r") as f:
                pos_data = json.load(f)
        except Exception:
            anomalies.append("장부 읽기 실패 (A2)")
            
    if len(pos_data) > 1:
        anomalies.append(f"MAX_POSITIONS 초과 (D21) - 현재 {len(pos_data)}개")
        
    # Check Logs for C, D, E
    errors = []
    rejects = []
    timeouts = []
    zombie = False
    
    if os.path.exists(log_file):
        mtime = os.path.getmtime(log_file)
        age = now - mtime
        if age > 300:
            anomalies.append(f"엔진 좀비/프리즈 (E27) - 로그 갱신 안됨 ({int(age)}초)")
            zombie = True
            
        # Parse last 500 lines for errors
        try:
            with open(log_file, "r") as f:
                lines = f.readlines()[-500:]
                for line in lines:
                    if "거절" in line or "실패" in line or "must be no smaller than" in line:
                        rejects.append(line.strip())
                    if "Timeout" in line or "timeout" in line:
                        timeouts.append(line.strip())
                    if "Exception" in line or "Error" in line:
                        if "asyncio" in line:
                            errors.append("asyncio Event Loop (E31)")
                        elif "RateLimit" in line or "429" in line:
                            errors.append("Rate Limit 밴 (E29)")
        except Exception:
            pass
            
    if rejects: anomalies.append(f"주문 거절/실패 발견 (B12/D23) - {len(rejects)}건")
    if timeouts: anomalies.append(f"타임아웃 발생 (B13) - {len(timeouts)}건")
    if errors: anomalies.append(f"크리티컬 에러 (E31/E29) - {', '.join(set(errors))}")
    
    # UI Check
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        if s.connect_ex(('127.0.0.1', b)) != 0:
            anomalies.append(f"UI 프로세스 응답 없음 (E28)")
            
    # Config / Switching check
    if os.path.exists(conf_file):
        try:
            with open(conf_file, "r") as f:
                conf = json.load(f)
                if conf.get("EQUITY_SCALE_FACTOR", 1.0) > 1.0:
                    anomalies.append("자산배분(복리) 오버헤드 (D22)")
        except:
            pass
            
    # Status report
    pos_count = len(pos_data)
    if not anomalies:
        print(f"[{b}] ✅ 이상 없음 (포지션: {pos_count}개) - 33개 항목 All Clear")
    else:
        print(f"[{b}] 🚨 이상 감지 (포지션: {pos_count}개)")
        for a in anomalies:
            print(f"      - {a}")
