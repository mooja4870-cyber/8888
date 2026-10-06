import re

with open("/Users/l/project/8888/discord_alert.py", "r") as f:
    content = f.read()

func_code = """
import re
import datetime

def _get_recent_bot_changes(days=14):
    try:
        with open(os.path.join(_DIR, "ver.md"), 'r') as f:
            v_content = f.read()
    except FileNotFoundError:
        return {}
        
    blocks = re.split(r'\\n## v', v_content)
    now = datetime.datetime.now()
    bot_changes = {str(b): [] for b in [8401, 8402, 8403, 8404, 8405, 8408, 8410]}
    
    for block in blocks[1:]:
        lines = block.strip().split('\\n')
        date_str = None
        change_text = []
        in_changes = False
        for line in lines:
            line = line.strip()
            if line.startswith("Date:"):
                date_str = line.split(":", 1)[1].strip()
            elif line.startswith("### 변경 내용"):
                in_changes = True
            elif in_changes and line.startswith("###"):
                in_changes = False
            elif in_changes and line:
                t = line.lstrip('*').strip()
                if t: change_text.append(t)
                
        if date_str:
            try:
                dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                if (now - dt).days <= days:
                    full_text = "\\n".join(change_text)
                    mentioned_bots = []
                    for b in bot_changes.keys():
                        if b in full_text: mentioned_bots.append(b)
                    
                    if not mentioned_bots and "전체 봇" in full_text:
                        mentioned_bots = list(bot_changes.keys())
                        
                    for b in mentioned_bots:
                        rel_lines = [l for l in change_text if b in l or "전체 봇" in l]
                        t = rel_lines[0] if rel_lines else change_text[0]
                        if len(t) > 40: t = t[:40] + "..."
                        bot_changes[b].append(f"({dt.strftime('%m/%d')}) {t}")
            except Exception:
                pass
                
    return {k: v for k, v in bot_changes.items() if v}

"""

tick_code = """
    ok1, info1 = _process_subset(data, group1, "_g1.json", "그룹 1", include_bot_charts=include_bot_charts)
    import time
    time.sleep(1) # 웹훅 레이트리밋 방지
    ok2, info2 = _process_subset(data, group2, "_g2.json", "그룹 2", include_bot_charts=include_bot_charts)
    
    # 최근 14일 설정 변경 요약 추가 발송
    try:
        changes = _get_recent_bot_changes(days=14)
        if changes:
            embeds = []
            desc = ""
            for b in sorted(changes.keys()):
                lines = "\\n".join([f"- {c}" for c in changes[b][:2]])
                desc += f"**[{b}]**\\n{lines}\\n\\n"
            if desc:
                embeds.append({
                    "title": "🛠️ 최근 14일 봇별 매매전략 및 설정 변경 요약",
                    "description": desc.strip(),
                    "color": 15158332
                })
                time.sleep(1)
                webhook_url = open(WEBHOOK_FILE, "r").read().strip()
                requests.post(webhook_url, json={"embeds": embeds}, timeout=10)
    except Exception as e:
        print(f"변경 요약 전송 실패: {e}")
        
    return ok1 or ok2, f"G1:{info1} / G2:{info2}"
"""

content = content.replace("def tick(data, tick_count=0, include_bot_charts=False):", func_code + "\ndef tick(data, tick_count=0, include_bot_charts=False):")

old_tick = 'ok1, info1 = _process_subset(data, group1, "_g1.json", "그룹 1", include_bot_charts=include_bot_charts)\n    import time\n    time.sleep(1) # 웹훅 레이트리밋 방지\n    ok2, info2 = _process_subset(data, group2, "_g2.json", "그룹 2", include_bot_charts=include_bot_charts)\n    \n    return ok1 or ok2, f"G1:{info1} / G2:{info2}"'

content = content.replace(old_tick, tick_code.strip())

with open("/Users/l/project/8888/discord_alert.py", "w") as f:
    f.write(content)
