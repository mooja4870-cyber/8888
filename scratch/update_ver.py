import os

new_version = "v11.5.0"
date = "2026-09-23"
content_to_add = f"""## {new_version}
Date: {date}

### 변경 내용
* `core/engine.py` 구조적 리팩토링 (재발 방지 대책 적용)
  - `_check_closed_positions_async` 함수 내부를 역할에 따라 2개로 완전히 분리
  - 장부 기록 전용 로직: `_sync_closed_positions_from_exchange`
  - 익절/손절 핵심 두뇌: `_evaluate_smart_exits`
  - `record_only` 옵션의 부작용을 구조적으로 원천 차단하여 안정성 확보

### 수정 파일
* core/engine.py

### 비고
* 10개 봇 전체 동일 구조 패치 및 컴파일 검증 완료

"""

for i in range(8401, 8411):
    filepath = f"/Users/l/project/{i}/ver.md"
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # insert after "# Version History\n\n"
    if "# Version History" in content:
        new_content = content.replace("# Version History\n", f"# Version History\n\n{content_to_add}")
    else:
        new_content = f"# Version History\n\n{content_to_add}\n" + content
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    print(f"[{i}] ver.md updated")

