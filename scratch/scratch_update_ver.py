import datetime

ver_file = '/Users/l/project/8407/ver.md'
with open(ver_file, 'r') as f:
    content = f.read()

today = datetime.datetime.now().strftime("%Y-%m-%d")
new_block = f"""## v11.6.0
Date: {today}

### 변경 내용
* [봇 전략 엔진 전면 교체] 8402(OKX) 봇의 매매 전략 및 설정값을 8407(Binance)에 100% 동일하게 이식 (사용자 지시)
  - 기존 딥러닝 방향예측(QPB) 폐기 및 트렌드 추종(Donchian) 전략 엔진 적용
* 설정값(config.json): 8402 파라미터 병합 (Binance 고유 식별정보 및 API 키는 보호 유지)
* UI 화면 교체: 8402 대시보드 코드를 이식하여 8407에 적용
* Binance / OKX 간 공통 `BinanceClient` 알리아스 활용을 통해 호환성 확보 및 백엔드 로그 3중 검증 완료

### 수정 파일
* config.json
* core/* (전략 엔진 및 매니저 파일 다수)
* app.py
* ui/* (대시보드 패널)
* ver.md

### 비고
* 백엔드 및 UI 프로세스 신규 로직으로 재기동 완료 및 정상 검증 완료

"""

# Insert right after "# Version History\n\n"
content = content.replace("# Version History\n\n", f"# Version History\n\n{new_block}")
if "v11.6.0" not in content:
    content = content.replace("# Version History\n", f"# Version History\n\n{new_block}")

with open(ver_file, 'w') as f:
    f.write(content)
