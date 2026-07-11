import re, os

base = "/Users/l/project"
bots = ["8407", "8408", "8409"]

for bot in bots:
    p = os.path.join(base, bot, "app.py")
    if not os.path.exists(p):
        continue
    
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()
        
    pattern = r'<span class="rainbow-text"(.*?style=".*?")>([0-9]{4})_Binance</span>'
    
    def repl(m):
        style_attr = m.group(1)
        new_style = style_attr.replace('style="', 'style="color:#ffffff; ')
        bot_num = m.group(2)
        return f'<span{new_style}>{bot_num}</span>'
    
    new_content, count = re.subn(pattern, repl, content)
    
    if count > 0:
        with open(p, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Updated {bot}/app.py (replacements: {count})")
    else:
        print(f"No match found in {bot}/app.py")

