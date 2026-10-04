import datetime

filepath = "/Users/l/project/8405/ver.md"
with open(filepath, "r") as f:
    content = f.read()

new_ver = f"""
## v1.7.13-bbmr

Date: {datetime.datetime.now().strftime("%Y-%m-%d")}

### 변경 내용
* 기존 15분봉 DonchianVol 전략에서 BB Mean Reversion (RSI < 30, SL = 2.5x ATR) 엔진으로 전면 교체 (Grid Search 최적화 결과 반영)
* USE_REGIME_ROUTER 비활성화

### 수정 파일
* core/strategy.py
* core/config.py

### 비고
* 대시보드(app.py) 동기화 파싱 확인 완료

"""

with open(filepath, "w") as f:
    f.write(content.replace("# Version History\n", f"# Version History\n{new_ver}"))
