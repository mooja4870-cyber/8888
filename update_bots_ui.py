import re
import os

base = "/Users/l/project"
bots = ["8401", "8402", "8404", "8406", "8407", "8408", "8409"]

for bot in bots:
    p = os.path.join(base, bot, "app.py")
    if not os.path.exists(p):
        continue
    
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Example to match: <span class="rainbow-text" style="font-size: 100%;">8401_OKX</span>
    # Or without font-size.
    # Replace `<span class="rainbow-text" ... >840X_OKX</span>` with `<span style="color:#ffffff; ...>840X</span>`
    
    # regex pattern
    pattern = r'<span class="rainbow-text"(.*?style=".*?")>([0-9]{4})_(?:OKX|BNC)</span>'
    
    def repl(m):
        style_attr = m.group(1)
        # remove any hue/animation/rainbow stuff if it's there
        # but inject color:#ffffff;
        # let's just make sure color:#ffffff is inside style
        # e.g. style="color:#ffffff; font-size:..."
        new_style = style_attr.replace('style="', 'style="color:#ffffff; ')
        bot_num = m.group(2)
        return f'<span{new_style}>{bot_num}</span>'
    
    new_content, count = re.subn(pattern, repl, content)
    
    # some might not have style attribute
    pattern2 = r'<span class="rainbow-text">([0-9]{4})_(?:OKX|BNC)</span>'
    def repl2(m):
        bot_num = m.group(1)
        return f'<span style="color:#ffffff; font-weight:bold;">{bot_num}</span>'
        
    new_content, count2 = re.subn(pattern2, repl2, new_content)
    
    if count > 0 or count2 > 0:
        with open(p, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Updated {bot}/app.py (replacements: {count + count2})")
    else:
        print(f"No match found in {bot}/app.py")

