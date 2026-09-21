import os

# 1. discord_alert.py
path1 = '/Users/l/project/8888/discord_alert.py'
with open(path1, 'r') as f:
    code1 = f.read()

old_tick = """def tick(data, tick_count=0, include_bot_charts=False):
    \"\"\"집계 1건을 받아 매 1분마다 디스코드 알림 발송 및 상태 갱신 (전체 봇 일괄 발송).\"\"\"
    all_bots = {str(b.get("name")) for b in data.get("bots", [])}
    if not all_bots:
        return False, "No bots in data"
    
    ok, info = _process_subset(data, all_bots, "_all.json", "전체", include_bot_charts=include_bot_charts)
    return ok, info"""

new_tick = """def tick(data, tick_count=0, include_bot_charts=False):
    \"\"\"집계 1건을 받아 매 1분마다 디스코드 알림 발송 및 상태 갱신 (그룹 1, 그룹 2 분할 발송).\"\"\"
    group1 = {"8401", "8402", "8410"}
    group2 = {"8403", "8405", "8407", "8409"}
    
    ok1, info1 = _process_subset(data, group1, "_g1.json", "그룹 1", include_bot_charts=include_bot_charts)
    import time
    time.sleep(1) # 웹훅 레이트리밋 방지
    ok2, info2 = _process_subset(data, group2, "_g2.json", "그룹 2", include_bot_charts=include_bot_charts)
    
    return ok1 or ok2, f"G1:{info1} / G2:{info2}" """

code1 = code1.replace(old_tick, new_tick)
with open(path1, 'w') as f:
    f.write(code1)

print("discord_alert.py done")
