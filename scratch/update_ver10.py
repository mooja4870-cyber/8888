import sys

def prepend_to_file(filename, content):
    with open(filename, 'r') as f:
        original = f.read()
    with open(filename, 'w') as f:
        f.write(content + "\n" + original)

content = """## v13.0.6
Date: 2026-09-20

### 변경 내용
* [보스 지시 반영] 8888 봇 통합 관제 대시보드 하단 차트를 '복합 차트(Dual-axis Chart)'로 업그레이드
* 차트 왼쪽(y축)은 '총자산 잔고($)', 오른쪽(y1축)은 '일평균수익률(%)'로 분리 렌더링
* 일평균수익률 데이터는 붉은색 선 그래프로 렌더링하여 가시성 확보 및 축간 혼선 제거
* 전체 탭 선택 시 각 봇의 `seed` 가중치를 반영한 전체 포트폴리오 일평균수익률 연산 로직 프론트엔드에 추가"""

prepend_to_file('ver.md', content)
