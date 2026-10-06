# Version History

## v1.2.17
Date: 2026-10-07

### 변경 내용
* [8402] 1일봉(1d) 추세추종 봇의 수학적 모순 해결을 위해 분할익절 완전 폐지 (USE_SCALEOUT: false)
* [8402] 손익비 극대화(RR 3.3)를 위해 익절 5.0 ATR, 손절 1.5 ATR로 재설정

### 수정 파일
* /Users/l/project/8402/config.json

### 비고
* 8402 봇 설정 변경 완료 및 디스코드 요약 알림 반영


## v1.5.0
Date: 2026-10-05

### 변경 내용
* 디스코드 알림 메시지에서 '최근 200분(5분봉) 전체 총자산 추이($)' 차트 출력 부분 제거

### 수정 파일
* discord_alert.py


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



## v1.2.8
Date: 2026-10-05

### 변경 내용
* 대시보드(dashboard.html) 하단의 '봇별 총자산 추이' 탭 목록 배열에 누락되어 있던 8403 봇 추가 완료

### 수정 파일
* dashboard.html

### 비고
* UI 정상 렌더링 확인 


## v1.2.9
Date: 2026-10-05

### 변경 내용
* 대시보드(app.py) 실자산 추이 렌더링 시 과거 데이터 표시 기간을 최대 7일로 제한하던 로직(`start_epoch` 필터) 삭제. 모든 봇이 초기화 이후부터 현재까지의 100% 전체 히스토리를 차트에 표출하도록 개선.

### 수정 파일
* app.py

### 비고
* UI 정상 렌더링 및 7일 이상 과거 데이터 정상 로드 확인 


## v1.2.10
Date: 2026-10-06

### 변경 내용
* watchdog_keeper.sh 스크립트를 개선하여 기존의 메인 감시망(watchdog_entry.py) 외에도 포지션 진입 워치독(watchdog_position.py)과 청산 워치독(watchdog_exit.py)까지 총 3개의 워치독 프로세스를 1분마다 전수 감시하고 자동 부활시키도록 로직 보강.
* 중단되어 있던 진입/청산 워치독 2개 백그라운드 강제 재기동 완료 (디스코드 알림 정상화).

### 수정 파일
* watchdog_keeper.sh

### 비고
* 진입/청산 3중 방어망 완전 복구 및 정상 작동 확인 완료


## v1.2.11
Date: 2026-10-06

### 변경 내용
* 8405 봇의 좀비 포지션(장기 체공 포지션) 연쇄 청산 현상을 원천 방어하기 위해 Time Stop(타임아웃) 룰 강화 적용
* MAX_HOLDING_HOURS를 48시간으로, MAX_HOLDING_HARD_HOURS를 72시간으로 대폭 축소하여 악성 재고 생성 차단
* 8402 봇 PID 락 꼬임 현상 해결 및 재기동

### 수정 파일
* /Users/l/project/8405/config.json

### 비고
* 백그라운드 봇 전체 100% 정상 가동 확인 (verify_all PASS)


## v1.2.12
Date: 2026-10-06

### 변경 내용
* 오진으로 인해 축소했던 8405 봇의 타임아웃 룰(MAX_HOLDING_HOURS)을 원래 수치(480h/720h)로 완벽 롤백
* 상승장(BULL) 고변동성 휩쏘 구간에서 잦은 기계적 손절(SL) 방어를 위해 손익절 버퍼 대폭 확대
  - GLOBAL_SL_PCT: 1.2% -> 2.0%
  - GLOBAL_TP_PCT: 2.5% -> 4.0%
  - DON_SL_ATR_MULT: 2.0 -> 3.0

### 수정 파일
* /Users/l/project/8405/config.json

### 비고
* 8405 재기동 및 전체 봇 100% 정상 가동 확인 (verify_all PASS)


## v1.2.13
Date: 2026-10-06

### 변경 내용
* 8410 봇의 상승장(BULL) 돌파매매 시 1시간봉 기준 휩쏘(고변동성)장세 방어를 위한 동적 손절/익절 버퍼 대폭 확장
  - ATR_SL_MULT: 1.5 -> 2.5
  - ATR_TP_MULT: 3.0 -> 5.0
  - DON_SL_ATR_MULT: 2.0 -> 3.0
* 통계적 휩쏘 구간에서 잦은 기계적 손절로 인한 연패(3승 8패) 현상 원천 차단

### 수정 파일
* /Users/l/project/8410/config.json

### 비고
* 8410 재기동 및 전체 봇 100% 정상 가동 확인 (verify_all PASS)


## v1.2.13
Date: 2026-10-06

### 변경 내용
* 8410 봇(비트코인/이더리움 등 메이저 코인 1시간봉 전략)의 상승장 휩쏘 방어력 대폭 상향
* 1시간봉 기준 깊은 조정을 견디기 위한 동적 손절/익절(ATR) 버퍼 확장
  - ATR_SL_MULT: 1.5 -> 2.5
  - ATR_TP_MULT: 3.0 -> 5.0
  - DON_SL_ATR_MULT: 2.0 -> 3.0
* 8401, 8402 등 타 봇의 좀비 프로세스/락 충돌 일괄 정리 및 복구

### 수정 파일
* /Users/l/project/8410/config.json

### 비고
* 8410 및 전체 봇 재기동, 100% 정상 가동 확인 (verify_all PASS)


## v1.2.14
Date: 2026-10-06

### 변경 내용
* 디스코드 알림 발송 그룹 편성 조정
  - 그룹 1: 8402, 8405, 8410
  - 그룹 2: 8401, 8403, 8404, 8408

### 수정 파일
* /Users/l/project/8888/discord_alert.py

### 비고
* 알림 그룹 분할 발송 로직 업데이트 완료


## v1.2.15
Date: 2026-10-06

### 변경 내용
* 8405의 쌍둥이 봇인 8403 봇에 동일한 상승장 휩쏘 방어 패치(백신) 이식 완료
  - GLOBAL_SL_PCT: 1.2% -> 2.0%
  - GLOBAL_TP_PCT: 2.5% -> 4.0%
  - DON_SL_ATR_MULT: 2.0 -> 3.0

### 수정 파일
* /Users/l/project/8403/config.json

### 비고
* 8403 재기동 및 전체 봇 100% 정상 가동 확인 (verify_all PASS)


## v1.2.16
Date: 2026-10-07

### 변경 내용
* 디스코드 알림 발송 시 '최근 14일 봇별 매매전략 및 설정 변경 요약'을 파싱하여 발송하는 로직 추가
* 디스코드 알림 발송 순서를 1) 최근 변경 요약 -> 2) 그룹2 -> 3) 그룹1 로 변경

### 수정 파일
* /Users/l/project/8888/discord_alert.py
