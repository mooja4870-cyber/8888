import re
import datetime

def get_recent_bot_changes(ver_path="/Users/l/project/8888/ver.md", days=14):
    try:
        with open(ver_path, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        return {}
        
    blocks = re.split(r'\n## v', content)
    now = datetime.datetime.now()
    
    bot_changes = {str(b): [] for b in [8401, 8402, 8403, 8404, 8405, 8408, 8410]}
    
    for block in blocks[1:]: # skip first empty or # Version History
        lines = block.strip().split('\n')
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
                change_text.append(line)
                
        if date_str:
            try:
                dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                if (now - dt).days <= days:
                    full_text = "\n".join(change_text)
                    # Check which bots are mentioned
                    mentioned_bots = []
                    for b in bot_changes.keys():
                        if b in full_text:
                            mentioned_bots.append(b)
                    
                    if not mentioned_bots and "전체 봇" in full_text:
                        mentioned_bots = list(bot_changes.keys())
                        
                    for b in mentioned_bots:
                        bot_changes[b].append(f"({dt.strftime('%m/%d')}) {full_text.splitlines()[0][:50]}...")
            except Exception as e:
                pass
                
    # Filter empty
    return {k: v for k, v in bot_changes.items() if v}

print(get_recent_bot_changes())
