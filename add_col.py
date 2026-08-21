import sys

with open("/Users/l/project/8888/dashboard.html", "r") as f:
    text = f.read()

text = text.replace(
    '<th style="padding:8px;text-align:center;font-weight:600">봇</th>\n     <th style="padding:8px;text-align:center">거래소</th>',
    '<th style="padding:8px;text-align:center;font-weight:600">봇</th>\n     <th style="padding:8px;text-align:center">초기화 잔고</th><th style="padding:8px;text-align:center">거래소</th>'
)

text = text.replace(
    '][순]</span>"}${b.name}</td>\n     <td style="padding:8px;text-align:center">${b.ex||"OKX"}</td>',
    '][순]</span>"}${b.name}</td>\n     <td style="padding:8px;text-align:center">$${(b.seed||0).toFixed(2)}</td><td style="padding:8px;text-align:center">${b.ex||"OKX"}</td>'
)

with open("/Users/l/project/8888/dashboard.html", "w") as f:
    f.write(text)

with open("/Users/l/project/8888/index.html", "r") as f:
    text2 = f.read()

text2 = text2.replace(
    '<th style="padding:8px;text-align:center;font-weight:600">봇</th>\n     <th style="padding:8px;text-align:center">거래소</th>',
    '<th style="padding:8px;text-align:center;font-weight:600">봇</th>\n     <th style="padding:8px;text-align:center">초기화 잔고</th><th style="padding:8px;text-align:center">거래소</th>'
)

text2 = text2.replace(
    '][순]</span>"}${b.name}</td>\n     <td style="padding:8px;text-align:center">${b.ex||"OKX"}</td>',
    '][순]</span>"}${b.name}</td>\n     <td style="padding:8px;text-align:center">$${(b.seed||0).toFixed(2)}</td><td style="padding:8px;text-align:center">${b.ex||"OKX"}</td>'
)

with open("/Users/l/project/8888/index.html", "w") as f:
    f.write(text2)

