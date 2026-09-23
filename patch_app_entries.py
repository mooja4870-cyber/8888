import re
import os

path = "/Users/l/project/8888/app.py"
with open(path, "r", encoding="utf-8") as f:
    code = f.read()

old_block = """    entries_by_period = {}
    for key, secs in periods.items():
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - secs))
        if ps and cutoff < ps:
            cutoff = ps
        # 1. 해당 윈도우 내에 진입한 거래 건수 산출
        entered_oids = set()
        for ts, oid in entries:
            if ts >= cutoff:
                entered_oids.add(oid)
        entries_by_period[key] = len(entered_oids)"""

new_block = """    # [v8.21.0] 활성화된 현재 포지션 진입 시각도 윈도우에 포함하여 진입 횟수 계산 (역사 초기화 후 누락 방지)
    active_entry_times = []
    try:
        apos_path = os.path.join(os.path.dirname(path), "active_positions.json")
        if os.path.exists(apos_path):
            import json
            with open(apos_path, "r", encoding="utf-8") as f:
                apos = json.load(f)
            for _, v in apos.items():
                ot = v.get("open_time")
                if ot:
                    # '2026-09-23T08:37:00.017619' 형식 지원
                    active_entry_times.append(ot.replace("T", " ")[:19])
    except Exception:
        pass

    entries_by_period = {}
    for key, secs in periods.items():
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - secs))
        if ps and cutoff < ps:
            cutoff = ps
        # 1. 해당 윈도우 내에 진입한 거래 건수 산출
        entered_oids = set()
        for ts, oid in entries:
            if ts >= cutoff:
                entered_oids.add(oid)
        
        # 현재 활성 포지션들의 진입 시각도 합산
        for i, ot in enumerate(active_entry_times):
            if ot >= cutoff:
                entered_oids.add(f"active_{i}")
                
        entries_by_period[key] = len(entered_oids)"""

if old_block in code:
    code = code.replace(old_block, new_block)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    print("Patched app.py entries_by_period successfully.")
else:
    print("Could not find old_block in app.py")
