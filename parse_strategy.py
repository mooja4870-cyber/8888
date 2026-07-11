import re, os
p = "/Users/l/project/8408/app.py"
text = open(p).read()
m = re.search(r'class="quantum-logo".*?title="([^"]+)', text, re.DOTALL | re.IGNORECASE)
if not m:
    m2 = re.search(r'title=([^\>]+)>', text, re.DOTALL)
    if m2:
        print("".join(re.findall(r'"(.*?)"', m2.group(1))))
else:
    print(m.group(1))
