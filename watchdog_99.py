import os
import time
import subprocess
import json
import requests
from datetime import datetime, timedelta

# 디스코드 웹훅 URL (bot_sentinel.py 등과 동일하게 사용)
DISCORD_WEBHOOK_URL = ""

def get_discord_webhook():
    # 8888 하위의 config 혹은 환경변수에서 읽어오기
    try:
        from core.config import CFG
        return CFG.DISCORD_WEBHOOK_URL
    except:
        return ""

BOT_DIRS = ["8401", "8402", "8403", "8404", "8405", "8408", "8410"]
BASE_PATH = "/Users/l/project"

class Watchdog99:
    def __init__(self):
        self.webhook = get_discord_webhook()

    def send_discord_alert(self, message):
        print(message)
        # 웹훅이 있으면 전송
        if self.webhook:
            try:
                payload = {"content": message}
                requests.post(self.webhook, json=payload, timeout=5)
            except Exception as e:
                print(f"Webhook send error: {e}")

    def run_check(self):
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🤖 99-Point Watchdog 가동 시작")
        
        for bot in BOT_DIRS:
            bot_path = os.path.join(BASE_PATH, bot)
            if not os.path.exists(bot_path) or os.path.exists(os.path.join(bot_path, '.stopped')):
                continue
                
            self._audit_bot(bot, bot_path)
            
    def _audit_bot(self, bot, bot_path):
        diagnostics = []
        is_critical = False
        action_taken = ""
        
        # 1. 프로세스 및 락 파일 상태 체크 (Point 76-80)
        bot_pid = None
        st_pid = None
        
        # bot.py 체크 (PID 파일 기반)
        pid_file = os.path.join(bot_path, "bot.pid")
        if os.path.exists(pid_file):
            try:
                with open(pid_file, "r") as f:
                    _pid = f.read().strip()
                if _pid.isdigit():
                    # 프로세스 생존 확인
                    if os.system(f"kill -0 {_pid} 2>/dev/null") == 0:
                        bot_pid = _pid
            except:
                pass

        # Streamlit 체크 (포트 번호 기반)
        try:
            out = subprocess.check_output(["ps", "aux"]).decode('utf-8')
            for line in out.splitlines():
                if "streamlit" in line.lower() and "app.py" in line and str(bot) in line:
                    st_pid = line.split()[1]
        except:
            pass
                
        lock_files = [f for f in ["bot.pid", "trader.lock", ".lock"] if os.path.exists(os.path.join(bot_path, f))]
        
        if bot_pid is None:
            diagnostics.append(f"❌ [프로세스 죽음] 봇 프로세스가 존재하지 않습니다.")
            is_critical = True
            
            # 자가 치유: 락 파일 강제 삭제 후 재기동
            if lock_files:
                for lf in lock_files:
                    try:
                        os.remove(os.path.join(bot_path, lf))
                    except:
                        pass
            
            p = subprocess.Popen(["python3", "bot.py"], cwd=bot_path, stdout=open(os.path.join(bot_path, "bot_stdout.log"), "a"), stderr=subprocess.STDOUT)
            with open(os.path.join(bot_path, "bot.pid"), "w") as f:
                f.write(str(p.pid))
            action_taken = "좀비 락 삭제 및 봇 강제 재기동 완료"
            
        if st_pid is None:
            diagnostics.append(f"❌ [UI 프로세스 죽음] Streamlit 프로세스가 존재하지 않습니다.")
            is_critical = True
            log_out = open(os.path.join(bot_path, "streamlit_server.log"), "a")
            subprocess.Popen(["nohup", "python3", "-m", "streamlit", "run", "app.py", "--server.port", bot], cwd=bot_path, stdout=log_out, stderr=subprocess.STDOUT)
            action_taken += " (Streamlit UI 자동 재기동 완료)"

        if bot_pid is not None:
            # 2. 로그 파일 에러 스캔 (Point 31-45, 46-65)
            log_path = os.path.join(bot_path, "bot.log")
            if os.path.exists(log_path):
                try:
                    # 마지막 100줄만 스캔
                    log_tail = subprocess.check_output(["tail", "-n", "100", log_path]).decode('utf-8')
                    if "Too Many Requests" in log_tail or "429" in log_tail:
                        diagnostics.append("⚠️ [API Rate Limit] 429 에러 발생 감지")
                    if "NaN" in log_tail or "Divide by Zero" in log_tail:
                        diagnostics.append("⚠️ [데이터 연산 오류] 지표 계산 중 NaN 발생 감지")
                    if "LOCK" in log_tail and "다른 트레이더 프로세스가" in log_tail:
                        diagnostics.append("❌ [LOCK 충돌] 좀비 프로세스 충돌 감지")
                        is_critical = True
                        os.system(f"kill -9 {bot_pid}")
                        for lf in lock_files:
                            try: os.remove(os.path.join(bot_path, lf))
                            except: pass
                        p = subprocess.Popen(["python3", "bot.py"], cwd=bot_path, stdout=open(os.path.join(bot_path, "bot_stdout.log"), "a"), stderr=subprocess.STDOUT)
                        with open(os.path.join(bot_path, "bot.pid"), "w") as f:
                            f.write(str(p.pid))
                        action_taken = "충돌 좀비 사살 및 재기동 완료"
                    if "Error" in log_tail and "connection" in log_tail.lower():
                        diagnostics.append("⚠️ [네트워크] 바이낸스 통신 타임아웃 감지")
                    if "attributeerror" in log_tail.lower() or "traceback (most recent" in log_tail.lower() or "exception" in log_tail.lower():
                        if "watchdog" not in log_tail.lower():
                            diagnostics.append("❌ [런타임 에러] 봇 내부 코드 에러 발생(AttributeError/Traceback 등). 포지션 진입 불가 상태!")
                            is_critical = True
                    if "종목 스캔 오류" in log_tail:
                        diagnostics.append("⚠️ [스캔 에러] 종목 스캔 중 파이썬 예외 발생. 진입 누락 위험!")
                        is_critical = True
                    if "신호 수신" in log_tail and "has no attribute" in log_tail:
                        diagnostics.append("❌ [진입 실패] 매매 신호가 발생했으나 내부 에러로 진입 거절됨!")
                        is_critical = True
                except Exception as e:
                    pass

            # 2-1. UI 로그 에러 및 스캐너 연동 스캔
            st_log_path = os.path.join(bot_path, "streamlit_server.log")
            if os.path.exists(st_log_path):
                try:
                    st_tail = subprocess.check_output(["tail", "-n", "50", st_log_path]).decode('utf-8').lower()
                    if "indentationerror" in st_tail or "syntaxerror" in st_tail or "traceback (most recent" in st_tail:
                        diagnostics.append("❌ [UI 런타임 에러] streamlit_server.log에서 심각한 런타임 에러(Traceback 등) 감지됨")
                        is_critical = True
                except:
                    pass

            json_path = os.path.join(bot_path, "scan_results.json")
            if os.path.exists(json_path):
                if os.path.getsize(json_path) < 10:
                    diagnostics.append("⚠️ [스캐너 오류] scan_results.json 파일이 비어 있습니다.")
            else:
                diagnostics.append("❌ [스캐너 누락] scan_results.json 파일이 존재하지 않습니다.")
                is_critical = True
        # 3. 장부(stats.json)와 거래소 상태 불일치 점검 (Point 71-75)
        stats_path = os.path.join(bot_path, "stats.json")
        has_internal_pos = False
        if os.path.exists(stats_path):
            try:
                with open(stats_path, "r") as f:
                    st = json.load(f)
                    pos = st.get("positions", {})
                    if pos:
                        has_internal_pos = True
            except:
                diagnostics.append("⚠️ [장부 오류] stats.json 파싱 실패 (JSON 깨짐)")
                
        # 4. 시장 진입 대기 (정상 상태 판별) (Point 81-99)
        # 만약 에러가 없고 포지션도 없다면, 정상 관망 상태로 판별
        if not diagnostics and not has_internal_pos:
            diagnostics.append("✅ [정상 관망] 타점 대기 중 (BB MR 이탈 또는 RSI 도달 대기)")
            
        # 심각한 에러나 조치가 취해졌다면 리포트 발송
        if is_critical or action_taken:
            msg = f"🚨 **[Watchdog-99 조기 조치 리포트]** `{bot}` 봇\n"
            msg += "\n".join([f"- {d}" for d in diagnostics])
            msg += f"\n🛠️ **조치 내용:** {action_taken}"
            self.send_discord_alert(msg)

if __name__ == "__main__":
    wd = Watchdog99()
    while True:
        try:
            wd.run_check()
        except Exception as e:
            print(f"Watchdog Error: {e}")
        time.sleep(300) # 5분 주기 감시
