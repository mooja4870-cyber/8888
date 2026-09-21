import os
import json
import re

bots = ["8401", "8402", "8403", "8404", "8405", "8406", "8407", "8408", "8409", "8410"]

print("=== 봇 상태 및 에러 검증 ===")

for b in bots:
    state_file = f"/Users/l/project/{b}/data/state.json"
    log_file = f"/Users/l/project/{b}/bot.log"
    
    holding = False
    
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                st = json.load(f)
            holding = st.get("holding", False)
            print(f"[{b}] holding={holding}")
        except Exception as e:
            print(f"[{b}] state.json 읽기 실패: {e}")
            
    # 최근 500줄 로그에서 에러 확인
    if os.path.exists(log_file):
        try:
            with open(log_file, 'rb') as f:
                # Seek to end and read last ~30KB
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 30000))
                lines = f.read().decode('utf-8', errors='ignore').split('\n')
                
            errors = []
            for line in lines:
                if re.search(r'(error|exception|fail|insufficient|margin|api|timeout|reject)', line, re.IGNORECASE):
                    # 너무 흔한 SSL 에러 등 필터링 가능, 일단 다 수집
                    if "Unclosed connector" not in line and "Event loop is closed" not in line and "Bad file descriptor" not in line and "SSL transport" not in line:
                        errors.append(line)
            
            if errors:
                print(f"[{b}] 최근 로그 에러 발견 ({len(errors)}건):")
                for e in errors[-5:]: # 최근 5개만
                    print(f"  > {e.strip()}")
            else:
                print(f"[{b}] 최근 로그 클린.")
        except Exception as e:
            print(f"[{b}] bot.log 읽기 실패: {e}")

