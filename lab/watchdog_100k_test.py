#!/usr/bin/env python3
import os
import re
import sys
import random
import time

BASE_DIR = "/Users/l/project"
BOTS = ["8401", "8402", "8403", "8404", "8405", "8408", "8410"]

print(">>> 1. 소스코드 전수 정적 분석: 실제 에러 키워드 스크래핑 시작...")

error_patterns = set()
python_files = []
for bot in BOTS:
    bot_path = os.path.join(BASE_DIR, bot)
    for root, dirs, files in os.walk(bot_path):
        for file in files:
            if file.endswith(".py") and not file.startswith("."):
                python_files.append(os.path.join(root, file))

for p in python_files:
    try:
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
            # Extract things inside logger.error("...") or logger.warning("...") or raise Exception("...")
            matches = re.findall(r'(?:logger\.error|logger\.warning|logger\.critical|Exception|ValueError|log)\s*\(\s*[f]?["\'](.*?)["\']', content)
            for m in matches:
                # Remove variables {var} from f-strings to get the raw text
                clean_m = re.sub(r'\{.*?\}', '', m).strip()
                if clean_m and len(clean_m) > 3:
                    error_patterns.add(clean_m)
    except Exception:
        pass

error_patterns = list(error_patterns)
print(f"✅ 총 {len(error_patterns)}개의 고유 에러 패턴 추출 완료.")

# 기존에 우리가 알고 있는 ERROR_KEYWORDS
CURRENT_ENTRY_KEYWORDS = [
    "NameError", "Exception", "Traceback", "Order failed",
    "진입 실패", "position error", "rate limit", "Too Many Requests", "조회 실패"
]
CURRENT_EXIT_KEYWORDS = [
    "청산 실패", "청산 에러", "Failed to close", "Error closing",
    "청산 감지 오류", "청산 기록 점검 실패", "종료 실패", "exit error", "close position error"
]

print("\n>>> 2. 10만 개 단위 카오스 테스트(퍼징) 준비 중...")

# Generate 100,000 test cases
# Mix of normal logs, known errors, and scraped hidden errors
total_tests = 100000
test_cases = []

normal_templates = [
    "봇 엔진 정상 기동", "캔들 데이터 수신 완료", "스캔 시작", 
    "포지션 없음", "시그널 없음 대기 중", "서버 핑 정상", 
    "디스코드 알림 발송", "정상 종료"
]

scraped_errors_to_inject = random.sample(error_patterns, min(50, len(error_patterns)))

for i in range(total_tests):
    rand_val = random.random()
    if rand_val < 0.8:
        # 80% Normal
        test_cases.append({"type": "normal", "msg": random.choice(normal_templates)})
    elif rand_val < 0.85:
        # 5% Generic Entry Error
        test_cases.append({"type": "entry_error", "msg": f"에러 발생: {random.choice(CURRENT_ENTRY_KEYWORDS)}"})
    elif rand_val < 0.90:
        # 5% Generic Exit Error
        test_cases.append({"type": "exit_error", "msg": f"에러 발생: {random.choice(CURRENT_EXIT_KEYWORDS)}"})
    else:
        # 10% Scraped Hidden Errors (The true test)
        test_cases.append({"type": "hidden_error", "msg": f"숨겨진 에러: {random.choice(scraped_errors_to_inject)}"})

print(f"✅ 100,000개 카오스 로그 엔트리 생성 완료.")

print("\n>>> 3. 워치독 감시망 방어율(Detection Rate) 테스트 시작...")

# 워치독 로직 에뮬레이션
def watchdog_detects(msg, keywords):
    msg_lower = msg.lower()
    for kw in keywords:
        if kw.lower() in msg_lower:
            return True
    return False

missed_entry_errors = []
missed_exit_errors = []
false_positives = 0

for tc in test_cases:
    is_detected_entry = watchdog_detects(tc["msg"], CURRENT_ENTRY_KEYWORDS)
    is_detected_exit = watchdog_detects(tc["msg"], CURRENT_EXIT_KEYWORDS)
    
    if tc["type"] == "normal":
        if is_detected_entry or is_detected_exit:
            false_positives += 1
    elif tc["type"] == "entry_error":
        if not is_detected_entry:
            missed_entry_errors.append(tc["msg"])
    elif tc["type"] == "exit_error":
        if not is_detected_exit:
            missed_exit_errors.append(tc["msg"])
    elif tc["type"] == "hidden_error":
        # Hidden errors might not be explicitly entry or exit, but they MUST be caught by at least ONE.
        if not (is_detected_entry or is_detected_exit):
            missed_entry_errors.append(tc["msg"]) # Treat as missed by the global net

print("\n==================================================")
print("📊 100,000 항목 극한 검증 테스트 결과")
print("==================================================")
print(f"정상 로그 오탐지(False Positive): {false_positives} 건")

total_missed = len(set(missed_entry_errors + missed_exit_errors))
defense_rate = ((100000 - total_missed) / 100000) * 100

print(f"워치독 에러 탐지 누락(Miss): {total_missed} 건 (방어율: {defense_rate:.2f}%)")

if total_missed > 0:
    print("\n[발견된 치명적 맹점 (새로 추가해야 할 키워드)]")
    # Extract just the raw keywords that failed
    blind_spots = set()
    for m in missed_entry_errors[:100]: # limit to 100 distinct
        blind_spots.add(m.replace("숨겨진 에러: ", ""))
    
    for bs in blind_spots:
        print(f" - {bs}")
    
    print("\n결론: 방어율 100% 달성 실패. 발견된 맹점(키워드)들을 워치독에 즉시 패치해야 합니다.")
else:
    print("\n결론: 워치독 방어율 100% 완벽 통과.")
