# Version History

## v1.7.9
Date: 2026-10-04

### 변경 내용
* 디스코드 알림 발송 시 8403 봇을 그룹2에서 그룹1로 이동 처리

### 수정 파일
* discord_alert.py
* send_discord_stats.py

### 비고
* 그룹 재배정


## v1.7.8
Date: 2026-10-04

### 변경 내용
* 8888 프로젝트 디스코드 알림 및 집계 대상 갱신 (8401, 8402, 8403, 8404, 8405, 8408, 8410)
* 신규 추가된 8403 봇을 디스코드 알림 시 '그룹2'로 할당

### 수정 파일
* app.py
* bot_watchdog.py
* discord_alert.py
* send_discord_stats.py

### 비고
* 대시보드 백엔드 프로세스 (app.py) 재기동 및 3중 검증 완료


## v1.7.7
Date: 2026-10-01

### 변경 내용
* [Watchdog] 진입 실패 감시망 대폭 강화 (포지션 진입 장애 관련 모든 키워드 및 미등록 에러(Unknown Error) 추적 로직 추가)
  * 추가 키워드: 네트워크/API 제한(NetworkError, RateLimit, Timeout, Connection reset), 데이터 조회 실패(fetch_tickers, fetch_ohlcv, NoneType, Empty DataFrame), 수량/마진 거절(-2019, Insufficient balance, ReduceOnly 등)
  * 미등록 에러 2중 그물망(Fallback): 최근 15분 내 ERROR 또는 Exception이 5회 이상 누적 시 강제 재기동하는 치명적 에러 감지 로직 이식

### 수정 파일
* /Users/l/project/8888/watchdog_entry.py

### 비고
* 스캐너 정체 및 알려지지 않은 예외에 의한 매매 멈춤 완벽 방어

