# Version History

## v1.2.52
Date: 2026-10-19

### 변경 내용
* [보스 특별 지침 반영: 5단계 최고 엄격 승인(Quintuple Approval) 규칙 대상 확대 개정]
  - `.agents/AGENTS.md`: 5단계 승인 대상 봇을 기존 2개(`8405, 8403`)에서 ➔ `8401, 8402, 8403, 8405` 총 4개 핵심 봇으로 확대 개정
  - 8401, 8402 봇의 매매전략·설정값·진입/청산 로직 변경 시에도 반드시 5단계 승인(사유/7대영역설계/리스크분석/Diff제시/검증확인)을 거치도록 통제 강화
  - 2단계 승인(Double Approval) 대상 봇은 `8404, 8408, 8410` 총 3개 봇으로 조정

### 수정 파일
* /Users/l/project/8888/.agents/AGENTS.md
* /Users/l/project/8888/ver.md

### 비고
* verify_all 100% PASS 검증 완료

## v1.2.51
Date: 2026-10-17

### 변경 내용
* [보스 특별 지침 반영: 관제 대시보드 총자산 추이 차트 툴팁 위치 개선]
  - `dashboard.html`: [봇별 총자산 추이] 차트(`_botAssetChart`)에서 마우스 호버 시 툴팁이 노란색 원형 동그라미(데이터 포인트)의 왼쪽을 가려 직전 구간 곡선 확인이 어렵던 현상 해결
  - `Chart.Tooltip.positioners.topPoint` 포지셔너 신규 등록: 활성 데이터셋 0번(노란색 자산 곡선)의 정확한 `(x, y)` 좌표에 툴팁 앵커 고정
  - `yAlign: 'bottom'`, `xAlign: 'center'`, `caretPadding: 8` 적용: 툴팁 꼬리표가 하단을 향하고 툴팁 본체는 노란색 원형 동그라미 바로 윗쪽에 깔끔하게 중앙 정렬되도록 개선
  - 차트 상단 패딩(`layout.padding.top: 35`) 추가: 최고점 부근에서도 툴팁이 상단 경계선에 잘리지 않도록 안전 여백 확보
  - 대시보드 내 모달 차트(`_assetChart`, `_retChart`, 개별 봇 모달) 툴팁에도 상단 정렬(`topPoint`) 일괄 적용하여 시각적 일관성 완성

### 수정 파일
* /Users/l/project/8888/dashboard.html
* /Users/l/project/8888/ver.md

### 비고
* verify_all 100% PASS 검증 완료

## v1.2.50
Date: 2026-10-17

### 변경 내용
* [8409, 8407 텔레그램 진입 알림 스코프 충돌(UnboundLocalError) 버그 해결]
  - `8409/core/trader.py`, `8407/core/trader.py`: `execute_entry` 내부 워치독 블록에 남아있던 중복 로컬 임포트(`from core.alert import send_telegram_alert`) 제거
  - 모듈 상단 글로벌 임포트가 함수 스코프 전역에 정상 적용되도록 하여 진입 완료 텔레그램 알림 누락 방지
  - 8409 TRX/USDT 실매매 체결 및 SL/TP 거래소 Algo 주문 활성화 상태 정상 확인

### 수정 파일
* /Users/l/project/8409/core/trader.py
* /Users/l/project/8407/core/trader.py
* /Users/l/project/8409/ver.md
* /Users/l/project/8407/ver.md
* /Users/l/project/8888/ver.md

### 비고
* verify_all 100% PASS 검증 완료

## v1.2.49
Date: 2026-10-16

### 변경 내용
* [8888 관제 알림 구형 백업 폴백 제거 및 유령 승패 시퀀스 완전 박멸]
  - `8888/extract_bot_metrics.py`: `trade_history.csv`가 비어있을 때 구형 `trade_history.csv.bak`을 읽어 유령 시퀀스를 만들어내던 결함 코드 완전 제거
  - 8407 및 8409: 삭제된 구형 QVT 전략의 잔재 백업 파일들(`trade_history.csv.bak*`)을 `_old_qvt_archive/` 디렉토리로 안전 격리
  - 8407, 8409의 승패 시퀀스를 공백(`""`)으로 정상화하고, 향후 신규 전략으로 실매매 체결 시에만 순수 1건씩 누적되도록 정합화 완료
  - 전체 10개 봇 장부 및 승패 시퀀스 전수 대조 점검 완료 (정상 7개 봇 실거래 100% 무결성 확인)

### 수정 파일
* /Users/l/project/8888/extract_bot_metrics.py
* /Users/l/project/8888/ver.md

### 비고
* verify_all 100% PASS 검증 완료

## v1.2.48
Date: 2026-10-16

### 변경 내용
* [단 한 번에 끝내는 3중 풀프루프(Foolproof) 시스템 공식 구축 및 verify_all 전면 고도화]
  - `verify_all.py` 풀프루프 검증 게이트 확장:
    1) 전체 활성 봇 포트(8401~8410) 실제 HTTP 200 OK 실측 검증
    2) `bot.log` 및 `bot_engine.log` 다중 엔진 로그 무결성(Traceback/AttributeError) 전수 감사
    3) 전체 활성 봇 대상 `config.json` ↔ `DASHBOARD_META` ↔ `8888/app.py` 파싱 타임프레임/전략명 100% 일치 강제 단언
  - `.agents/AGENTS.md`에 '3중 풀프루프 실행 규칙' 영구 표준 명시:
    1) 지시 매트릭스(Instruction Matrix) 단언 의무화
    2) UI 위젯의 Passive Overwrite 금지 및 on_change 콜백 표준화
    3) verify_all 100% PASS 증빙 없는 완료 보고 전면 금지

### 수정 파일
* /Users/l/project/8888/verify_all.py
* /Users/l/project/8888/.agents/AGENTS.md
* /Users/l/project/8888/ver.md

### 비고
* verify_all 100% PASS 검증 완료

## v1.2.47
Date: 2026-10-16

### 변경 내용
* [8409 타임프레임 1h 영구 고정 및 Streamlit 세션 충돌 버그 원천 해결]
  - `8409/app.py`: `st.selectbox`가 기존 브라우저 세션 캐시(15m)를 읽어 서버 `config.json`을 덮어쓰던 버그 원천 수정
  - `init_session`에서 `sidebar_tf_select`를 `CFG.TIMEFRAME`("1h")으로 초기화하고, `on_change` 이벤트 기반 콜백으로 전환하여 passive overwrite 차단
  - `8409/core/config.py`: `EXCHANGE_ID`를 바이낸스 자아에 맞게 `"binance"`로 일치
  - `8409/config.json`: `"TIMEFRAME": "1h"`, `"DASHBOARD_META": "BB MR (1h)"` 영구 고정
  - `8407/app.py` 및 `8407/core/config.py`: 동일한 세션 안정화 패치 동시 적용
  - 8409 봇 프로세스(`bot.py` + `app.py`) 재기동 및 1h 캔들 25개 종목 정상 스캔 검증 완료

### 수정 파일
* /Users/l/project/8409/app.py
* /Users/l/project/8409/core/config.py
* /Users/l/project/8409/config.json
* /Users/l/project/8409/ver.md
* /Users/l/project/8407/app.py
* /Users/l/project/8407/core/config.py
* /Users/l/project/8407/ver.md
* /Users/l/project/8888/ver.md

### 비고
* verify_all 100% PASS 검증 완료

## v1.2.46
Date: 2026-10-16

### 변경 내용
* [타임프레임 최적화 동기화] 8407(15m) 및 8409(1h) 타임프레임 차별화 반영
  - 8407: 8405와 동일한 15m 타임프레임 유지 (BB MR 15m)
  - 8409: 1h 타임프레임으로 전환 (BB MR 1h), config.json, core/config.py 동기화
  - 8888/app.py: read_bot_config()에서 8409를 1h 타임프레임으로 자동 인식하도록 동기화
  - 8409 봇 프로세스(`bot.py` + `app.py`) 재기동 및 1h 캔들 스캔 정상 확인

### 수정 파일
* /Users/l/project/8409/config.json
* /Users/l/project/8409/core/config.py
* /Users/l/project/8409/ver.md
* /Users/l/project/8888/app.py
* /Users/l/project/8888/ver.md

### 비고
* 보스 명시적 승인(OK) 후 반영 및 verify_all 100% PASS 검증 완료

## v1.2.45
Date: 2026-10-16

### 변경 내용
* [봇 이식 및 7대 영역 전수 동기화] 8405(OKX)의 BB MR(볼린저 밴드 평균회귀, 15m, 1개 보유, 66% 동적 복리 사이징) 전략을 8407(Binance) 및 8409(Binance) 두 봇에 완전 이식
  - 8407, 8409의 바이낸스 고유 자아(Identity: API 키, 계정 정보, 대시보드 포트 8407, 8409) 100% 보존
  - 기존 QVT 1h 매매 엔진, 설정값, 데이터클래스, UI 완전 삭제 후 8405 BB MR(15m, 66-33-11 동적 복리 사이징) 두뇌 및 UI 이식
  - 8888 중앙 관제소(app.py) 동시 수정: 8407, 8409 타임프레임(15m) 및 전략명(BB MR 15m) 실시간 파싱 동기화
  - 디스코드 알림(discord_alert.py) 동시 수정: 8407, 8409를 유형1(QVT)에서 유형2(BB MR 평균회귀) 그룹으로 재분류
  - 8407/ver.md, 8409/ver.md 각각 v2.1.0 갱신 및 백그라운드 봇(`bot.py` + `app.py`) 재기동 완료

### 수정 파일
* /Users/l/project/8407/* (core, config.json, bot.py, app.py, ver.md)
* /Users/l/project/8409/* (core, config.json, bot.py, app.py, ver.md)
* /Users/l/project/8888/app.py
* /Users/l/project/8888/discord_alert.py
* /Users/l/project/8888/ver.md

### 비고
* 보스 명시적 승인(OK) 후 반영 및 verify_all 100% PASS 검증 완료

## v1.2.44
Date: 2026-10-16

### 변경 내용
* [디스코드 알림 순서 개편] 매매전략 유형별 발송 순서를 유형1,2,3에서 유형3,2,1 역순으로 재배치
  - discord_alert.py: 발송 루프의 순서를 유형3 Various Fusion(8404, 8408, 8410) ➔ 유형2 BB MR(8403, 8405) ➔ 유형1 QVT 스나이퍼(8401, 8402, 8407, 8409) 순으로 개편하여 디스코드 채널 상단에 유형3이 최우선 노출되도록 조정

### 수정 파일
* /Users/l/project/8888/discord_alert.py
* /Users/l/project/8888/ver.md

### 비고
* 보스 명시적 승인(OK) 후 반영 및 verify_all 100% PASS 검증 완료

## v1.2.43
Date: 2026-10-14

### 변경 내용
* [승인 체계 전면 격상 및 타겟 한정] 8405, 8403 봇 전용 5단계 승인 의무(5-Step Approval) 규칙 신설
  - .agents/AGENTS.md: 워치독 헬스체커에 의한 프로세스 자가 재기동을 제외하고, 8405 및 8403 두 개 봇의 모든 매매전략 변경, 설정값(파라미터/타임프레임/손익절) 변경, 포지션 진입/청산 방법 변경 시 반드시 보스의 5회 승인(1단계 필요성 ➔ 2단계 7대영역 설계 ➔ 3단계 리스크분석 ➔ 4단계 diff ➔ 5단계 최종 배포)을 받도록 시스템 영구 장착
  - .agents/AGENTS.md: 기존 2회 승인(Double Approval) 대상 봇을 8401, 8402, 8404, 8408, 8410 총 5개 핵심 봇으로 명확히 재분류

### 수정 파일
* /Users/l/project/8888/.agents/AGENTS.md
* /Users/l/project/8888/ver.md

### 비고
* 보스 명시적 지침 및 단독 승인 후 영구 규칙 법제화 완료

## v1.2.42
Date: 2026-10-14

### 변경 내용
* [승패 시퀀스 복원 및 누락 버그 영구 픽스] 알림 문구의 최근 30개 청산 실적 승패 흐름(seq) perf_start 종속 분리
  - extract_bot_metrics.py: 승패 시퀀스(seq) 추출 시 튜닝 시작일자(perf_start) 종속을 분리하여, 전략 리셋/개조 여부와 무관하게 전체 이력 중 가장 최근 30건을 언제나 온전하게 추출하도록 개편
  - extract_bot_metrics.py: trade_history.csv가 초기화된 봇(8404 등)의 경우 trade_history.csv.bak 파일에서 이전 청산 이력을 자동 복원하여 알림 문구에서 승패 흐름 줄이 생략되던 침묵 버그 원천 차단
  - app.py: extract_bot_metrics 서브프로세스 타임아웃을 2초에서 5초로 안전하게 확대하여 타임아웃 시 seq 빈값 초기화 위험 차단

### 수정 파일
* /Users/l/project/8888/extract_bot_metrics.py
* /Users/l/project/8888/app.py
* /Users/l/project/8888/ver.md

### 비고
* 디스코드 알림 메시지 8404 복원 실측 및 verify_all 100% PASS 검증 완료

## v1.2.41
Date: 2026-10-14

### 변경 내용
* [관제소 손익절 파싱 및 메타 전수 정합화] 보스 정밀 감사 지침에 따른 7대 영역 불일치 원천 제거
  - 8888/app.py: read_bot_config 손익절 파싱 로직에서 SL_ATR_MULT, ATR_SL_MULT, BBTS_SL_ATR_MULT 지원 (8404 등 고정 % 오표기 제거 및 ATR×1.5 / ATR×3.0 100% 반영)
  - 8404: config.json DASHBOARD_META에 sl_str/tp_str 명시 주입
  - 8410: core/config.py TradingConfig에 DASHBOARD_META 선언 (UI 설정 저장 시 키 증발 위험 원천 차단)
  - 8408: DASHBOARD_META 전략명을 1시간봉 가동 사실에 맞게 "BBTS 변동성 확장 돌파 (1h)"로 정합화
  - verify_all.py: 8404, 8408, 8410에 대한 7대 영역 정합성 및 DASHBOARD_META 선언 교차 감사 확장

### 수정 파일
* /Users/l/project/8888/app.py
* /Users/l/project/8888/verify_all.py
* /Users/l/project/8888/ver.md
* /Users/l/project/8404/config.json
* /Users/l/project/8404/ver.md
* /Users/l/project/8408/config.json
* /Users/l/project/8408/ver.md
* /Users/l/project/8410/core/config.py
* /Users/l/project/8410/ver.md

### 비고
* verify_all 100% PASS 검증 완료

## v1.2.40
Date: 2026-10-14

### 변경 내용
* [내부 강제 기준 확립] 보스 지침에 따라 전략 변경 및 기능 수정 시 '7대 영역 전수 일체형 동기화 규칙 (Full-Stack + 8888 중앙 관제소 Sync)' 수립 및 시스템 영구 장착
  - 1) 개별 봇 매매 엔진 (strategy.py)
  - 2) 개별 봇 설정 파일 (config.json)
  - 3) 개별 봇 데이터클래스 (core/config.py)
  - 4) 개별 봇 사이드바 UI (app.py)
  - 5) 개별 봇 관제 메타 (DASHBOARD_META)
  - 6) 중앙 관제소 8888 앱 동시 수정 (8888/app.py 파싱 및 화면 표시 동기화)
  - 7) 버전 이력 및 Git 동시 배포 (ver.md & commit/tag/push)
* [자가 검증 고도화] verify_all.py에 8888 중앙 관제소 ↔ 개별 봇 7대 영역 정합성 교차 감사 로직 장착 (타임프레임 불일치 및 메타 유실 원천 차단)

### 수정 파일
* /Users/l/project/8888/.agents/AGENTS.md
* /Users/l/project/8888/verify_all.py
* /Users/l/project/8888/ver.md

### 비고
* verify_all 100% PASS 검증 완료

## v1.2.39
Date: 2026-10-14

### 변경 내용
* [8404 / 8410 UI 및 설정 전수 정합화] 8404(SQUEEZE-HURST)와 8410(FUSION)의 사이드바 표기 및 config.json 설정값 100% 동기화
  - 8404: TIMEFRAME 1h 확정, 사이드바 하단 매매설정 박스 TTM 스퀴즈+허스트 퓨전 표기, 손익절 1.5/3.0 동기화
  - 8410: DASHBOARD_META 퓨전 정합화 및 청산 위젯 캡션 퓨전 다이내믹 표기 갱신
  - 백엔드 봇 엔진 및 Streamlit UI 재기동 및 3중 자체 검증 완료

### 수정 파일
* /Users/l/project/8404/config.json
* /Users/l/project/8404/app.py
* /Users/l/project/8404/ver.md
* /Users/l/project/8410/config.json
* /Users/l/project/8410/app.py
* /Users/l/project/8410/ver.md
* /Users/l/project/8888/ver.md

### 비고
* verify_all 100% PASS 검증 완료

## v1.2.38
Date: 2026-10-14

### 변경 내용
* [유형 3 명칭 변경] 보스 지침에 따라 유형 3의 분류 명칭을 'BBTS 추세돌파'에서 'Various Fusion (다양한 퓨전)'으로 전면 개편
  - 사유: 8404(TTM 스퀴즈+허스트 퓨전) 및 8410(ADX 국면적응 퓨전) 등 복합 퓨전 모델들을 아우르는 최적 명칭 정합화
  - 반영: discord_alert.py (디스코드 3유형 브리핑 타이틀), dashboard.html (관제 대시보드 폰트 색상 및 범례)

### 수정 파일
* discord_alert.py
* dashboard.html
* ver.md

### 비고
* verify_all 100% PASS 검증 완료

## v1.2.37
Date: 2026-10-14

### 변경 내용
* [8404 전략 전면 개조] 8404 봇에 TTM 스퀴즈 + 허스트 지수(Hurst) 하이브리드 퓨전(전략 15) 탑재
  - R/S 프랙탈 허스트 지수(H)와 볼린저-켈트너 TTM 스퀴즈를 융합하여 횡보장 MR 단타와 추세장 BBTS 돌파를 동적 실행
  - 8404 타임프레임 1h 최적화 및 8888 통합 관제 대시보드 메타(DASHBOARD_META) 동기화
  - 8888 관제소 대시보드 메타 우선 적용 로직 보강

### 수정 파일
* /Users/l/project/8404/core/strategy.py
* /Users/l/project/8404/core/config.py
* /Users/l/project/8404/config.json
* /Users/l/project/8404/app.py
* /Users/l/project/8404/ver.md
* /Users/l/project/8888/app.py
* /Users/l/project/8888/ver.md

### 비고
* 8404 매매 엔진 및 UI 정상 기동 확인, verify_all 100% PASS

## v1.2.36
Date: 2026-10-13

### 변경 내용
* [8410 UI 동기화] 8410 대시보드 사이드바 타이틀 및 매매 설정 실제 적용값 표기 정합화
  - 사이드바 타이틀: `8410 [BBTS 변동성 돌파]` ➔ `8410 [FUSION 퓨전 탄력매매]`
  - 호버 툴팁: 퓨전 메커니즘 (ADX<25 횡보 MR 회귀 / ADX>=25 추세 BBTS 돌파) 반영
  - 매매 설정 실제 적용값: `· 전략 볼린저 밴드 돌파` ➔ `· 전략 유형2+유형3 퓨전 (MR+BBTS)`

### 수정 파일
* /Users/l/project/8410/app.py
* /Users/l/project/8410/ver.md
* /Users/l/project/8888/ver.md

### 비고
* 8410 UI 포트 8410 정상 렌더링 및 verify_all 100% PASS 검증 완료

## v1.2.35
Date: 2026-10-13

### 변경 내용
* [8410 퓨전 매매전략] 8410 봇에 유형2 (BB MR 평균회귀) + 유형3 (BBTS 추세돌파) 탄력적 퓨전(FUSION) 전략 탑재
  - 추세 강도 지표(ADX 14) 기반 실시간 국면 판별 (ADX < 25: 횡보 MR 회귀 매매 / ADX >= 25: 추세 BBTS 돌파 매매)
* [트랙 레코드 리셋] 지난 42일간 서로 다른 8차례 수정 이력을 별도 분리 백업(`trade_history_legacy_42d.csv`)하고, 순수 단일 퓨전 전략 1일차 트랙 레코드 클린 스타트 (`stats.json` 시작시점 리셋)
* [워치독 오탐 안정화] `watchdog_exit.py`, `watchdog_position.py`, `error_dict.txt`에서 정상 국면 전환 로그(`[REGIME]`) 오탐 필터링 및 안정화 완료

### 수정 파일
* /Users/l/project/8410/core/strategy.py
* /Users/l/project/8410/config.json
* /Users/l/project/8410/data/stats.json
* /Users/l/project/8410/data/trade_history.csv
* /Users/l/project/8410/ver.md
* /Users/l/project/8888/watchdog_exit.py
* /Users/l/project/8888/watchdog_position.py
* /Users/l/project/8888/error_dict.txt
* /Users/l/project/8888/ver.md

### 비고
* 8410 봇 퓨전 전략 실시간 정상 가동 및 verify_all 100% PASS 검증 완료

## v1.2.34
Date: 2026-10-13

### 변경 내용
* [디스코드 알림 개편] 정기 알림에서 기존 경과일수 기반 그룹1~4 및 구분선 제거, 매매전략 유형1, 2, 3 단독 순차 발송으로 개편
  - 유형1 QVT 눌림목 스나이퍼 (8401, 8402, 8407, 8409)
  - 유형2 BB MR 평균회귀 (8403, 8405)
  - 유형3 BBTS 추세돌파 (8404, 8408, 8410)

### 수정 파일
* discord_alert.py
* ver.md

### 비고
* 8888 디스코드 알림 파이프라인 최적화 및 단독 발송 검증 완료

## v1.2.33
Date: 2026-10-13

### 변경 내용
* [시드 머니 동기화] 8404 봇의 초기화 기준 잔고를 9.68 USDT에서 10.0 USDT로 수정
  - 8404 `data/stats.json`: seed_money 10.0 적용
  - 8888 `seeds.json`: 8404 seed 10.0 동기화

### 수정 파일
* seeds.json
* ver.md

### 비고
* 8404 봇 대시보드 누적 수익률 산출 기준금 10.0 USDT 정상 반영 완료

## v1.2.32
Date: 2026-10-13

### 변경 내용
* [UI 개선] 대시보드(dashboard.html) '봇별 총자산 추이' 하단 탭 버튼에 매매전략 유형별 폰트 색상 적용
  - 유형1 (노랑): 8401, 8402, 8407, 8409 (QVT 눌림목 스나이퍼)
  - 유형2 (빨강): 8403, 8405 (BB MR 평균회귀)
  - 유형3 (파랑): 8404, 8408, 8410 (BBTS 추세돌파)
  - 선택(Active) 탭 하이라이트 및 발광(Glow) 효과 추가로 시인성 대폭 강화

### 수정 파일
* dashboard.html
* ver.md

### 비고
* 8888 관제 대시보드 봇별 총자산 추이 탭 버튼 시인성 개선 완료

## v1.2.31
Date: 2026-10-12

### 변경 내용
* [디스코드 알림 헤더 커스텀] 유형1~3 상단 헤더 문구를 각 전략 고유 명칭으로 변경
  - `유형1 QVT 눌림목 스나이퍼` (8401, 8402, 8407, 8409)
  - `유형2 BB MR 평균회귀` (8403, 8405)
  - `유형3 BBTS 추세돌파` (8404, 8408, 8410)
* [검증] 전체 봇 verify_all.py 100% PASS 확인 완료

### 수정 파일
* /Users/l/project/8888/discord_alert.py
* /Users/l/project/8888/ver.md

### 비고
* 디스코드 전략별 성과 알림 헤더 시인성 대폭 향상

## v1.2.30
Date: 2026-10-12

### 변경 내용
* [디스코드 알림 파이프라인 개편] 그룹1~4 -> '******* ******* *******' -> 유형1~3 순차 발송 구현
  - 그룹1~4: 초기화 경과일수 기준 4개 그룹 발송
  - 구분선: '******* ******* *******' 단독 메시지 전송
  - 유형1~3: 전략 패밀리별 3개 그룹 발송
    * 유형1: 8401, 8402, 8407, 8409 (QVT 눌림목 스나이퍼 전략)
    * 유형2: 8403, 8405 (BB MR 평균회귀 전략)
    * 유형3: 8404, 8408, 8410 (BBTS 추세돌파 전략)
* [알림 문구 서식 일원화] 매 1분 알림 시에도 초기화 이후 경과 일수(b_days, 예: 27.4) 상시 표기 적용
* [검증] 전체 봇 verify_all.py 100% PASS 확인 완료

### 수정 파일
* /Users/l/project/8888/discord_alert.py
* /Users/l/project/8888/ver.md

### 비고
* 디스코드 정기 알림 순서 보장 및 전략 유형별 성과 집계 완비

## v1.2.29
Date: 2026-10-11

### 변경 내용
* [UI 개선] 8888 대시보드(dashboard.html) 하단 '봇별 총자산 추이' 탭 목록에 8407, 8409 탭 추가
* [차트 연동] 8407 및 8409 선택 시 실자산 잔고($) 추이 차트 즉시 렌더링 지원
* [검증] 전체 봇 verify_all.py 100% PASS 확인 완료

### 수정 파일
* /Users/l/project/8888/dashboard.html
* /Users/l/project/8888/ver.md

### 비고
* 8888 관제 대시보드 '봇별 총자산 추이' 탭 9개 봇(8401~8410) 완비

## v1.2.28
Date: 2026-10-11

### 변경 내용
* [관제 확장] 8888 앱 관제 및 집계 대상에 8407(BNC), 8409(BNC) 추가 (총 9개 봇 실시간 모니터링 체제)
* [디스코드 그룹 개편] 초기화 이후 경과일수(perf_start) 기준 4개 그룹 동적 분류 적용
  - 그룹1 (7일 이내): 8401, 8402, 8403, 8407, 8409
  - 그룹2 (14일 이내): 8404
  - 그룹3 (21일 이내): 8408
  - 그룹4 (21일 초과): 8405, 8410
* [실시간 알림 정합] 그룹1~4 개별 상태 및 요약 순차 발송 정상 검증 (HTTP 204 확인)
* [검증] 전체 봇 verify_all.py 100% PASS 확인 완료

### 수정 파일
* /Users/l/project/8888/app.py
* /Users/l/project/8888/discord_alert.py
* /Users/l/project/8888/ver.md

### 비고
* 8888 관제 대시보드 9개 봇 HTML 반영 및 디스코드 4개 그룹 동적 발송 정상 확인

## v1.2.27
Date: 2026-10-11

### 변경 내용
* [8407, 8409] 바이낸스 선물 API 연동 정합 및 백그라운드 엔진(bot.py + app.py) 동시 기동 완료
* [8407, 8409] 8408 바이낸스 거래소 어댑터(BinanceClient) 및 api.md 연동 모듈 적용으로 잔고/포지션/스캔 정상 작동 확인
* [디스코드] '🛠️ 봇별 매매전략 및 설정 변경 요약' 파싱 대상에 8407, 8409 추가하여 이식 내역 실시간 알림 반영
* [검증] 전체 봇 verify_all.py 100% PASS 확인 완료

### 수정 파일
* /Users/l/project/8888/discord_alert.py
* /Users/l/project/8888/ver.md
* /Users/l/project/8407/ (core/exchange.py, core/api_keys.py, bot.py, app.py, ver.md)
* /Users/l/project/8409/ (core/exchange.py, core/api_keys.py, bot.py, app.py, ver.md)

### 비고
* 8407, 8409 백그라운드 동시 기동 및 디스코드 요약 알림 정합 완료

## v1.2.26
Date: 2026-10-11

### 변경 내용
* [Transplant] 8402 [QVT 눌림목 스나이퍼 (1h)]를 8401(OKX), 8407(Binance), 8409(Binance)로 완전 이식
* [자아 보존] 타겟 봇들의 API 인증키(.env, api.md), 포트 번호(8401, 8407, 8409), 거래소 식별자(OKX/Binance) 100% 보존
* [뇌/껍데기 이식] 타겟 봇 기존 core, config.json, app.py, bot.py 완전 삭제 후 8402 QVT 스나이퍼 엔진 복사
* [8401 기동] 8401 봇 엔진 즉시 재기동 및 QVT 눌림목 신호 실시간 스캔 확인 (FIL 롱 주문 정상 접수)
* [8407, 8409] 바이낸스 선물 환경 정합 완료 및 구문 컴파일(py_compile) 100% 검증 완료

### 수정 파일
* /Users/l/project/8401/ (core/, config.json, app.py, bot.py, ver.md)
* /Users/l/project/8407/ (core/, config.json, app.py, bot.py, ver.md)
* /Users/l/project/8409/ (core/, config.json, app.py, bot.py, ver.md)
* /Users/l/project/8888/ver.md

### 비고
* 보스 이중 승인 획득 후 안전 이식 및 verify_all 100% PASS 확인 완료

## v1.2.25
Date: 2026-10-11

### 변경 내용
* [8402] QVT 눌림목 스나이퍼 전략(v2.0.0)으로 전면 리빌딩 (월 4~7% 안정 수익 타깃)
* [8402] 4h EMA50/200 추세 게이트 및 Kaufman KER 횡보장 휩소 차단 필터 적용
* [8402] 1h RSI 눌림목 및 볼린저 지지 반등 트리거 + 손익비 1:3.0 (SL 1.5% / TP 4.5% / BE 2.0%)
* [8402] 최대 포지션 2개 슬롯 압축 (.5 마진 집중) 및 36.9일 통계 아카이브 분리

### 수정 파일
* /Users/l/project/8402/config.json
* /Users/l/project/8402/core/strategy.py
* /Users/l/project/8402/core/trader.py
* /Users/l/project/8402/data/stats.json
* /Users/l/project/8402/ver.md

### 비고
* 8402 봇 재기동 및 3중 검증(파일/UI/백엔드), verify_all 100% PASS 확인 완료


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

## v1.2.18
Date: 2026-10-07

### 변경 내용
* 디스코드 알림 발송 시 '최근 14일 봇별 매매전략 및 설정 변경 요약'에서 매매 전략과 무관한 단순 설정(그룹 편성, 디스코드 알림 등) 로그 필터링 처리

### 수정 파일
* discord_alert.py

### 비고
* 사용자의 명시적 요청에 의한 알림 가독성 증대

## v1.2.19
Date: 2026-10-07

### 변경 내용
* [8410] 마이너스 전환된 수익성 턴어라운드를 위한 수익 확보 강화 (Whipsaw 방어 수치 롤백 및 보호막 가동)
* [8410] ATR 기반 손절/익절 버퍼 원상 복구 (ATR_SL_MULT: 2.5 -> 1.5, ATR_TP_MULT: 5.0 -> 3.0, DON_SL_ATR_MULT: 3.0 -> 2.0)
* [8410] 트레일링 스탑(Trailing Stop) 강력 개입 활성화 (USE_TRAILING_STOP: true)
* [8410] 분할 익절 활성화 (USE_PARTIAL_TP: true)

### 수정 파일
* /Users/l/project/8410/config.json

### 비고
* Whipsaw 방어 명목의 과도한 리스크 노출 차단 및 확정 수익 위주의 로직으로 롤백 완료

## v1.2.20
Date: 2026-10-07

### 변경 내용
* [8402, 8403, 8405] 최근 수익률 저하 및 승률 악화 개선을 위한 수익 수호 장치(방어막) 전면 재가동
* ATR 기반 손절/익절 버퍼 원상 복구 및 하향 조정 (DON_SL_ATR_MULT 3.0 -> 2.0 등)
* 트레일링 스탑(Trailing Stop) 개입 활성화 (USE_TRAILING_STOP: true)
* 분할 익절 활성화 (USE_PARTIAL_TP: true)

### 수정 파일
* /Users/l/project/8402/config.json
* /Users/l/project/8403/config.json
* /Users/l/project/8405/config.json

### 비고
* Whipsaw 방어 명목의 과도한 리스크 노출 차단 및 확정 수익 위주의 로직으로 롤백 완료

## v1.2.21
Date: 2026-10-09

### 변경 내용
* 대시보드(dashboard.html) UI 하단 자산 추이 차트에서 '전체' 탭 완전히 삭제 처리
* 초기 로딩 시 기본 선택 탭을 '8401'로 변경

### 수정 파일
* dashboard.html

### 비고
* UI 정상 렌더링 검증 완료, 전체 시스템(verify_all) 100% PASS 확인

## v1.2.22
Date: 2026-10-10

### 변경 내용
* [8402] 역매매(청개구리) 모드 중단 및 정방향 추세추종 전환 (USE_BLUEFROG: false)
* [8402] 타임프레임을 1일(1d)에서 1시간(1h)으로 단축하여 월 4~7% 타겟 맞춤
* [8402] 최대 허용 손절폭 확장 (MAX_SL_PCT: 1.5% -> 5%)으로 노이즈 손절 방어
* [8402] 돌파 채널 길이 24, 거래량 필터 1.2 등 최적화 적용

### 수정 파일
* /Users/l/project/8402/config.json
* /Users/l/project/8402/core/config.py

### 비고
* 8402 재기동 및 전체 시스템(verify_all) 100% PASS 확인 완료

## v1.2.24
Date: 2026-10-10

### 변경 내용
* 디스코드 알림 발송 시 '최근 14일 봇별 설정 변경 요약'을 '봇별 매매전략 및 설정 변경 요약'으로 타이틀 변경
* 기간(14일) 필터를 해제하고 시기에 관계없이 봇별로 가장 최신 변경 내역 5개를 역순(최신순)으로 출력하도록 파싱 로직 수정

### 수정 파일
* discord_alert.py

### 비고
* 단독 테스트 및 verify_all 스크립트 전수 검사 PASS
