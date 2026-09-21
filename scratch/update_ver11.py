import sys

def prepend_to_file(filename, content):
    with open(filename, 'r') as f:
        original = f.read()
    with open(filename, 'w') as f:
        f.write(content + "\n" + original)

content = """## v13.0.7
Date: 2026-09-20

### 변경 내용
* [보스 지시 반영] 복합 차트의 보조 지표를 '일평균수익률'에서 '최근 24시간 롤링 단기 수익률(Rolling 24h Return)'로 변경
* `app.py`: 최근 24시간 전의 자산을 기준으로 실시간 수익률을 연산하는 `rolling_history` 필드 추가
* `dashboard.html`: 듀얼 차트 렌더링 시 우측 Y축 데이터 및 범례 라벨을 `최근 24h 수익률(%)`로 수정하여 총자산과 완전히 다른 차별화된 모멘텀 제공"""

prepend_to_file('ver.md', content)
