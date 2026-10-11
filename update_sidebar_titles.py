#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_sidebar_titles.py — 7개 핵심 봇 대시보드(app.py) 사이드바 타이틀 일괄 수정
"""
import re
import py_compile

BOT_TITLES = {
    "8401": "8401 [QVT 변동성 돌파]",
    "8402": "8402 [QVT 눌림목 스나이퍼]",
    "8403": "8403 [BB 평균회귀]",
    "8404": "8404 [QVT 변동성 돌파]",
    "8405": "8405 [BB 평균회귀]",
    "8408": "8408 [BBTS 변동성 돌파]",
    "8410": "8410 [BBTS 변동성 돌파]",
}

def update_bot_app(bot_id, title):
    app_path = f"/Users/l/project/{bot_id}/app.py"
    with open(app_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 패턴 1: 84xx_<span style="color:blue;">BlueFrog</span>
    pattern1 = rf'{bot_id}_<span style="color:blue;">BlueFrog</span>'
    # 패턴 2: 84xx_BlueFrog
    pattern2 = rf'{bot_id}_BlueFrog'

    new_span = f'{title}'
    
    modified = False
    if re.search(pattern1, content):
        content = re.sub(pattern1, new_span, content)
        modified = True
    elif re.search(pattern2, content):
        content = re.sub(pattern2, new_span, content)
        modified = True
    else:
        # 광범위한 BlueFrog 패턴 탐색
        pattern_broad = rf'{bot_id}[^<]*<span[^>]*>BlueFrog</span>'
        if re.search(pattern_broad, content):
            content = re.sub(pattern_broad, new_span, content)
            modified = True

    if modified:
        with open(app_path, "w", encoding="utf-8") as f:
            f.write(content)
        # 구문 검사
        py_compile.compile(app_path, doraise=True)
        print(f"[{bot_id}] SUCCESS -> '{title}' 적용 및 컴파일 검증 완료")
        return True
    else:
        print(f"[{bot_id}] WARNING -> 패턴을 찾지 못했습니다.")
        return False

def main():
    success_count = 0
    for bot_id, title in BOT_TITLES.items():
        if update_bot_app(bot_id, title):
            success_count += 1
    print(f"\n총 {len(BOT_TITLES)}개 중 {success_count}개 봇 app.py 사이드바 타이틀 수정 완료.")

if __name__ == "__main__":
    main()
