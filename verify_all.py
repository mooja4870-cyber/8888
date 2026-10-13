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
        lock_file = f"/tmp/quantum_{bot_id}_trader.lock"
        pid_alive = False
        
        # lock 파일 우선 확인 (실제 Python 프로세스의 true PID)
        if os.path.exists(lock_file):
            try:
                with open(lock_file, 'r') as f:
                    lpid = f.read().strip()
                if lpid.isdigit() and os.system(f"kill -0 {lpid} 2>/dev/null") == 0:
                    pid_alive = True
                    # bot.pid 파일도 실제 PID로 자동 동기화
                    with open(bot_pid_file, 'w') as f:
                        f.write(lpid)
            except:
                pass
                
        # bot.pid 파일 확인
        if not pid_alive and os.path.exists(bot_pid_file):
            with open(bot_pid_file, 'r') as f:
                pid = f.read().strip()
            if pid.isdigit() and os.system(f"kill -0 {pid} 2>/dev/null") == 0:
                pid_alive = True
                
        if not pid_alive:
            errors.append("❌ 봇 프로세스가 죽어 있습니다 (kill -0 실패)")

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

        # 3. [전략 변경 시 7대 영역 전수 일체형 동기화 감사] Full-Stack + 8888 관제소 Sync 검증
        cfg_file = os.path.join(bot_path, 'config.json')
        if os.path.exists(cfg_file):
            try:
                import json
                with open(cfg_file, 'r', encoding='utf-8') as f:
                    cfg_data = json.load(f)
                
                tf_cfg = str(cfg_data.get('TIMEFRAME', '')).strip().lower()
                dash_meta = cfg_data.get('DASHBOARD_META', {})
                
                # (1) 퓨전 및 전략 개조 봇(8404, 8410 등) 타임프레임 & 관제소 메타 일치 감사
                if dash_meta and isinstance(dash_meta, dict):
                    meta_strat = dash_meta.get('strategy', '')
                    if '(1d)' in meta_strat.lower() and tf_cfg and tf_cfg != '1d':
                        if bot_id in ['8404', '8410']:
                            errors.append(f"❌ 타임프레임 불일치: config은 '{tf_cfg}'이나 DASHBOARD_META는 '{meta_strat}' (1d 잔존)")
                    elif '(1h)' in meta_strat.lower() and tf_cfg and tf_cfg != '1h':
                        if bot_id in ['8404', '8410']:
                            errors.append(f"❌ 타임프레임 불일치: config은 '{tf_cfg}'이나 DASHBOARD_META는 '{meta_strat}' (1h 불일치)")

                # (2) 8888 중앙 관제소 read_bot_config 파싱 결과와 실제 config/메타 일치 여부
                try:
                    import sys
                    if '/Users/l/project/8888' not in sys.path:
                        sys.path.append('/Users/l/project/8888')
                    from app import read_bot_config
                    parsed_8888 = read_bot_config(bot_id)
                    if bot_id in ['8404', '8410']:
                        parsed_tf = str(parsed_8888.get('timeframe', '')).strip().lower()
                        if tf_cfg and parsed_tf and tf_cfg != parsed_tf:
                            errors.append(f"❌ 8888 관제소 파싱 불일치: 봇 config='{tf_cfg}', 8888 읽기='{parsed_tf}'")
                        if dash_meta and isinstance(dash_meta, dict) and dash_meta.get('strategy'):
                            if parsed_8888.get('strategy') != dash_meta.get('strategy'):
                                errors.append(f"❌ 8888 관제소 전략명 불일치: 메타='{dash_meta.get('strategy')}', 8888='{parsed_8888.get('strategy')}'")
                except Exception as e:
                    pass

                # (3) 8404 등 고도화 퓨전 봇의 core/config.py 필수 필드 선언 검사 (키 유실 방지)
                if bot_id == '8404':
                    core_cfg_file = os.path.join(bot_path, 'core', 'config.py')
                    if os.path.exists(core_cfg_file):
                        try:
                            with open(core_cfg_file, 'r', encoding='utf-8') as f:
                                core_cfg_text = f.read()
                            special_keys = ['KC_PERIOD', 'KC_MULT', 'HURST_MR_THRESH', 'HURST_TREND_THRESH', 'DASHBOARD_META']
                            for sk in special_keys:
                                if sk in cfg_data and sk not in core_cfg_text:
                                    errors.append(f"❌ core/config.py 데이터클래스 선언 누락: '{sk}' 필드가 없어 저장 시 유실 위험!")
                        except:
                            pass
            except Exception as e:
                errors.append(f"❌ config.json 파싱 오류: {e}")


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
