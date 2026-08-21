import sys, re

with open("/Users/l/project/8888/dashboard.html", "r") as f:
    text = f.read()

text = text.replace(
    '<td style="padding:8px;text-align:center">$${(b.seed||0).toFixed(2)}</td>',
    '<td style="padding:8px;text-align:center">${(b.seed===null||b.seed===undefined)?"—":"$"+(+b.seed).toFixed(2)}</td>'
)

with open("/Users/l/project/8888/dashboard.html", "w") as f:
    f.write(text)

with open("/Users/l/project/8888/index.html", "r") as f:
    text2 = f.read()

text2 = text2.replace(
    '<td style="padding:8px;text-align:center">$${(b.seed||0).toFixed(2)}</td>',
    '<td style="padding:8px;text-align:center">${(b.seed===null||b.seed===undefined)?"—":"$"+(+b.seed).toFixed(2)}</td>'
)

with open("/Users/l/project/8888/index.html", "w") as f:
    f.write(text2)

