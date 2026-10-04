import os
import glob
import subprocess

def verify_all():
    base_path = '/Users/l/project'
    bots = [d for d in glob.glob(f'{base_path}/84*') if os.path.isdir(d) and 'backup' not in d]
    bots.sort()

    all_pass = True
    print("==================================================")
    print("🔍 에이전트 자가 강제 검증 프로세스 시작 (verify_all)")
    print("==================================================")

    for bot_path in bots:
        bot_id = os.path.basename(bot_path)
        
        # 의도적으로 중지된 봇은 검사에서 제외
        if os.path.exists(os.path.join(bot_path, '.stopped')):
            print(f"[{bot_id}] SKIP ⏸️ (의도적 중지 상태)")
            continue
            
        errors = []
        
        # 1. Process checks
        bot_pid_file = os.path.join(bot_path, 'bot.pid')
        if os.path.exists(bot_pid_file):
            with open(bot_pid_file, 'r') as f:
                pid = f.read().strip()
            if pid.isdigit():
                if os.system(f"kill -0 {pid} 2>/dev/null") != 0:
                    errors.append("❌ 봇 프로세스가 죽어 있습니다 (kill -0 실패)")
        else:
            errors.append("❌ bot.pid 파일이 없습니다")

        # Streamlit check
        try:
            out = subprocess.check_output(["ps", "aux"]).decode('utf-8')
            st_running = any("streamlit" in line.lower() and bot_id in line for line in out.splitlines())
            if not st_running:
                errors.append("❌ Streamlit UI 프로세스가 없습니다")
        except:
            pass

        # 2. Log Integrity (Traceback, AttributeError)
        bot_log = os.path.join(bot_path, 'bot.log')
        if os.path.exists(bot_log):
            try:
                tail = subprocess.check_output(["tail", "-n", "200", bot_log]).decode('utf-8').lower()
                if "attributeerror" in tail or "traceback (most recent" in tail:
                    errors.append("❌ 봇 로그에 파이썬 런타임 에러(AttributeError/Traceback)가 존재합니다!")
            except:
                pass
                
        st_log = os.path.join(bot_path, 'streamlit_server.log')
        if os.path.exists(st_log):
            try:
                tail = subprocess.check_output(["tail", "-n", "100", st_log]).decode('utf-8').lower()
                if "indentationerror" in tail or "syntaxerror" in tail or "traceback (most recent" in tail:
                    errors.append("❌ UI 로그에 코드 레벨 에러가 존재합니다!")
            except:
                pass

        # 3. Print Results
        if errors:
            print(f"[{bot_id}] FAIL 💥")
            for err in errors:
                print(f"   -> {err}")
            all_pass = False
        else:
            print(f"[{bot_id}] PASS ✅")

    print("==================================================")
    if all_pass:
        print("결론: 100% PASS - 모든 시스템이 정상 구동 중입니다.")
    else:
        print("결론: FAIL - 에러가 발견되었습니다. 문제 해결 프로세스로 돌아가십시오.")
        
    return all_pass

if __name__ == "__main__":
    import sys
    if not verify_all():
        sys.exit(1)
    sys.exit(0)
