import sys, re

with open("/Users/l/project/8888/dashboard.html", "r") as f:
    text = f.read()

text = re.sub(
    r'(<th style="padding:8px;text-align:center;font-weight:600">봇</th>\s*<th style="padding:8px;text-align:center">거래소</th>)',
    r'<th style="padding:8px;text-align:center;font-weight:600">봇</th>\n     <th style="padding:8px;text-align:center">초기화 잔고</th><th style="padding:8px;text-align:center">거래소</th>',
    text
)

text = re.sub(
    r'(\]</span>"\}\$\{b.name\}</td>\s*<td style="padding:8px;text-align:center">\$\{b.ex\|\|"OKX"\}</td>)',
    r']</span>"}${b.name}</td>\n     <td style="padding:8px;text-align:center">$${(b.seed||0).toFixed(2)}</td><td style="padding:8px;text-align:center">${b.ex||"OKX"}</td>',
    text
)

with open("/Users/l/project/8888/dashboard.html", "w") as f:
    f.write(text)

with open("/Users/l/project/8888/index.html", "r") as f:
    text2 = f.read()

text2 = re.sub(
    r'(<th style="padding:8px;text-align:center;font-weight:600">봇</th>\s*<th style="padding:8px;text-align:center">거래소</th>)',
    r'<th style="padding:8px;text-align:center;font-weight:600">봇</th>\n     <th style="padding:8px;text-align:center">초기화 잔고</th><th style="padding:8px;text-align:center">거래소</th>',
    text2
)

text2 = re.sub(
    r'(\]</span>"\}\$\{b.name\}</td>\s*<td style="padding:8px;text-align:center">\$\{b.ex\|\|"OKX"\}</td>)',
    r']</span>"}${b.name}</td>\n     <td style="padding:8px;text-align:center">$${(b.seed||0).toFixed(2)}</td><td style="padding:8px;text-align:center">${b.ex||"OKX"}</td>',
    text2
)

with open("/Users/l/project/8888/index.html", "w") as f:
    f.write(text2)

