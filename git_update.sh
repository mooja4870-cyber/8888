#!/bin/bash
DATE=$(date "+%Y-%m-%d")

# 8406
cd /Users/l/project/8406
cat << MD > ver.md
# Version History

## v1.0.1
Date: $DATE

### 변경 내용
* 8410(Binance) 로직 이식 완료
* OKX 환경에 맞춰 거래소 클라이언트 분기(app.py, bot.py, engine.py) 패치 적용
* trailing_stop_manager.py 내 BTC/USDT 심볼 환경변수 기반 유연화 패치 적용

### 수정 파일
* bot.py, app.py, core/engine.py
* core/trailing_stop_manager.py
* config.json
MD
git add .
git commit -m "feat: 8410 to 8406(OKX) transplant and cross-exchange patching"
git tag v1.0.1
git push origin main
git push origin v1.0.1

# 8408
cd /Users/l/project/8408
cat << MD > ver.md
# Version History

## v1.0.1
Date: $DATE

### 변경 내용
* 8410(Binance) 로직 이식 완료
* trailing_stop_manager.py 내 BTC/USDT 심볼 환경변수 기반 유연화 패치 적용

### 수정 파일
* 모든 핵심 엔진 및 대시보드 로직
MD
git add .
git commit -m "feat: 8410 to 8408(Binance) transplant"
git tag v1.0.1
git push origin main
git push origin v1.0.1

# 8404
cd /Users/l/project/8404
cat << MD > ver.md
# Version History

## v1.0.2
Date: $DATE

### 변경 내용
* trailing_stop_manager.py 내 BTC/USDT 심볼 하드코딩 제거 및 환경변수(REGIME_REF_SYMBOL) 기반 유연화 적용 (OKX 심볼 에러 해결)

### 수정 파일
* core/trailing_stop_manager.py
MD
git add .
git commit -m "fix: trailing_stop_manager BTC symbol hardcode for OKX"
git tag v1.0.2
git push origin main
git push origin v1.0.2
