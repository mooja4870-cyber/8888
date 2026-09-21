import sys

def prepend_to_file(filename, content):
    with open(filename, 'r') as f:
        original = f.read()
    with open(filename, 'w') as f:
        f.write(content + "\n" + original)

content = """## v11.2.10
Date: 2026-09-20

### 변경 내용
* [보스 특별 지침 반영] 8888 봇 통합 관제 대시보드 하단 '봇별 총자산 추이' 차트 UI 추가
* '전체' 및 개별 봇 탭 선택 시 해당 봇의 `asset_history` 시계열 데이터 연동 (Chart.js 적용)
* 8406, 8408 봇을 집계에서 제외하고, 각 개별 차트 탭에서는 렌더링되도록 구현 (데이터 구조 분리)
* JS 초기화 지연(TDZ) 오류 해결을 위한 _selectedBotForAsset 전역 변수 선언 위치 수정
* chartData 바인딩을 `b.metrics`에서 참조하도록 논리적 매핑 오류 개선 완료"""

prepend_to_file('ver.md', content)
