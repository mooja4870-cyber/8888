import os
import json
import time
import socket
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("watchdog")

def run_33_point_audit(bot_id: int, cwd: str) -> list:
    """
    33대 건강 검진을 수행하고 이상 항목들의 리스트를 반환합니다.
    이상이 없으면 빈 리스트 [] 를 반환합니다.
    """
    pos_file = os.path.join(cwd, "data", "active_positions.json")
    log_file = os.path.join(cwd, "bot_engine.log")
    conf_file = os.path.join(cwd, "config.json")
    
    anomalies = []
    now = time.time()
    
    # 1. 장부 무결성 및 Max Position 확인
    pos_data = []
    if os.path.exists(pos_file):
        try:
            with open(pos_file, "r") as f:
                pos_data = json.load(f)
        except Exception:
            anomalies.append("장부 읽기 실패 (A2)")
            
    if len(pos_data) > 1:
        anomalies.append(f"MAX_POSITIONS 초과 (D21) - 현재 {len(pos_data)}개")
        
    # 2. 엔진 로그 파싱 (에러, 거절, 타임아웃, 프리즈 확인)
    errors = []
    rejects = []
    timeouts = []
    
    if os.path.exists(log_file):
        mtime = os.path.getmtime(log_file)
        age = now - mtime
        if age > 300:
            anomalies.append(f"엔진 좀비/프리즈 (E27) - 로그 갱신 안됨 ({int(age)}초)")
            
        try:
            with open(log_file, "r") as f:
                # 마지막 500줄 파싱
                lines = f.readlines()[-500:]
                for line in lines:
                    if "거절" in line or "실패" in line or "must be no smaller than" in line or "-4164" in line:
                        rejects.append(line.strip())
                    if "Timeout" in line or "timeout" in line:
                        timeouts.append(line.strip())
                    if "Exception" in line or "Error" in line:
                        if "asyncio" in line:
                            errors.append("asyncio Event Loop (E31)")
                        elif "RateLimit" in line or "429" in line or "IP ban" in line:
                            errors.append("Rate Limit 밴 (E29)")
        except Exception as e:
            pass
            
    if rejects: anomalies.append(f"주문 거절/실패 발견 (B12/D23) - 최근 500줄 내 {len(rejects)}건")
    if timeouts: anomalies.append(f"타임아웃 발생 (B13) - 최근 500줄 내 {len(timeouts)}건")
    if errors: anomalies.append(f"크리티컬 에러 감지 (E31/E29) - {', '.join(set(errors))}")
    
    # 3. UI 리스닝 포트 응답 확인
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        if s.connect_ex(('127.0.0.1', bot_id)) != 0:
            anomalies.append(f"UI 대시보드 포트 응답 없음 (E28)")
            
    # 4. Config 검증 및 자가 교정
    if os.path.exists(conf_file):
        try:
            with open(conf_file, "r") as f:
                conf = json.load(f)
                
            config_changed = False
            
            # AUTO_TRADING 꺼짐 감지 및 강제 교정
            if conf.get("AUTO_TRADING") is False:
                anomalies.append("AUTO_TRADING 꺼짐 (자동매매 불가 상태) -> 강제 ON 교정")
                conf["AUTO_TRADING"] = True
                config_changed = True
                
            # 자산배분(복리) 오버헤드 감지
            if conf.get("EQUITY_SCALE_FACTOR", 1.0) > 1.0:
                anomalies.append("자산배분(복리) 1.0 오버헤드 초과 (D22)")
                
            if config_changed:
                with open(conf_file, "w") as f:
                    json.dump(conf, f, indent=4)
        except Exception as e:
            pass

    # 5. 장부(stats.json) 좀비 쿨다운 모순 상태 검증 및 자가 복구
    stats_file = os.path.join(cwd, "data", "stats.json")
    if os.path.exists(stats_file):
        try:
            with open(stats_file, "r") as f:
                stats = json.load(f)
                
            stats_changed = False
            
            # 5-1. 좀비 쿨다운 상태 검증 및 자가 복구
            if stats.get("halted_by_consec_sl") is True and stats.get("daily_consec_sl", 0) == 0:
                anomalies.append("좀비 쿨다운 상태 감지 (0연속 손절 락) -> 강제 해제 조치 완료")
                stats["halted_by_consec_sl"] = False
                stats_changed = True
                
            # 5-2. 자정 리셋 누락 상태 검증 및 자가 복구 (KST 기준)
            today_kst = (datetime.utcnow() + timedelta(hours=9)).date().isoformat()
            if stats.get("today_date") != today_kst:
                if stats.get("daily_pnl_usdt", 0.0) != 0.0 or stats.get("orders_today", 0) != 0:
                    anomalies.append(f"자정 리셋 누락 감지 (과거 날짜 데이터 잔존) -> 강제 리셋 완료")
                    stats["today_date"] = today_kst
                    stats["daily_pnl_usdt"] = 0.0
                    stats["orders_today"] = 0
                    stats_changed = True
                    
            # 5-3. 만료된 종목 쿨다운 방치 상태 검증 및 청소
            s_cd = stats.get("symbol_cooldown_until", {})
            if s_cd:
                now = datetime.now()
                cleaned_cd = {}
                stale_found = False
                for sym, iso_str in s_cd.items():
                    try:
                        dt = datetime.fromisoformat(iso_str)
                        if dt > now:
                            cleaned_cd[sym] = iso_str
                        else:
                            stale_found = True
                    except:
                        stale_found = True
                
                if stale_found:
                    anomalies.append("만료된(혹은 오염된) 종목 쿨다운 방치 감지 -> 청소 완료")
                    stats["symbol_cooldown_until"] = cleaned_cd
                    stats_changed = True

            if stats_changed:
                with open(stats_file, "w") as f:
                    json.dump(stats, f, indent=4)
        except Exception as e:
            pass

    return anomalies
