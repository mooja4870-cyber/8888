#!/bin/bash
# 이 스크립트는 Antigravity IDE의 Stop Hook에 의해 호출됩니다.
# 에이전트가 작업을 마치고 사용자에게 응답하려고 할 때마다 백그라운드에서 실행됩니다.

# verify_all.py 실행
python3 /Users/l/project/8888/verify_all.py > /dev/null 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  # 실패 시: 에이전트의 종료(Stop)를 강제로 막고(continue), 에러 메시지를 주입합니다.
  echo '{"decision": "continue", "reason": "🔥 [SYSTEM BLOCK] verify_all.py 검증 스크립트가 실패했습니다! 봇 중에 죽어있거나 에러가 난 봇이 있습니다. 100% PASS를 달성할 때까지 작업을 멈출 수 없습니다. 로그를 확인하고 즉시 고치세요!"}'
else
  # 성공 시: 빈 객체를 반환하여 에이전트의 정상 종료를 허용합니다.
  echo '{}'
fi
