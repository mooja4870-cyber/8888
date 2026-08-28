# 🔴 BOT 설정 긴급 수정 (2026-08-28)

## 수정 완료

### BOT 8401 (OKX) - 5m_Scalping_Copilot
**문제:** RR 비율 역전 (TP < SL)
- ❌ STOP_LOSS_PCT: 0.03 → ✅ 0.025 (2.5%)
- ❌ TAKE_PROFIT_PCT: 0.025 → ✅ 0.05 (5%)
- ❌ MAX_SL_PCT: 0.15 → ✅ 0.08 (8%)
- **효과:** RR 비율 2:1로 개선 (원래는 0.83배 역전)

### BOT 8408 (Binance) - SNIPER 스윙
**문제:** 좀비 포지션 위험 (MAX_HOLDING 20일)
- ❌ MAX_HOLDING_HARD_HOURS: 480 → ✅ 240 (10일)
- **효과:** 장기 보유 손실 감소

### BOT 8410 (Binance) - BBTS
**문제:** 설정 오류 (120%, 250% 값)
- ❌ GLOBAL_SL_PCT: 1.2 → ✅ 0.12 (12%)
- ❌ GLOBAL_TP_PCT: 2.5 → ✅ 0.25 (25%)
- ❌ DAILY_LOSS_LIMIT_USDT: 7 → ✅ 50 ($50)
- **효과:** 정상 작동

## 재시작 필요
- 8401: 즉시 재시작 필요
- 8408: 즉시 재시작 필요
- 8410: 즉시 재시작 필요

## 참고
- 8403, 8409: 동결 중 (08-16~09-15 수정 금지)
- 8402, 8404, 8407: 추가 수정 없음

## 🔴 추가 수정 (2026-08-28 17:35)

### BOT 8407 (Binance) - 딥러닝
**문제:** AttributeError - CFG.USE_RSI_FILTER 누락
- ✅ config.json: USE_RSI_FILTER 속성 추가
- ✅ app.py:829: `CFG.USE_RSI_FILTER` → `getattr(CFG, "USE_RSI_FILTER", True)`

### BOT 8404 (OKX) - QVT-ARE
**문제:** StreamlitValueAboveMaxError - MAX_SL_PCT 초과
- ✅ config.json: MAX_SL_PCT 0.15 → 0.1 (streamlit max=10%)

### 상태
✅ 8407: 재시작 완료 (정상 작동)
✅ 8404: 재시작 완료 (정상 작동)
