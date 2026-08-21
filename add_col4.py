import sys, re

with open("/Users/l/project/8888/dashboard.html", "r") as f:
    text = f.read()

text = text.replace(
    '<tr style="background:#181b22;"><td>총 잔고${exwarn}</td><td><span style="font-size:155%;font-weight:bold">${usd(b.ex_balance)}</span></td></tr>',
    '<tr style="background:#181b22;"><td>초기 자본</td><td><span style="font-size:125%;font-weight:bold">${usd(b.seed)}</span></td></tr>\n     <tr style="background:#181b22;"><td>총 잔고${exwarn}</td><td><span style="font-size:155%;font-weight:bold">${usd(b.ex_balance)}</span></td></tr>'
)

with open("/Users/l/project/8888/dashboard.html", "w") as f:
    f.write(text)

with open("/Users/l/project/8888/index.html", "r") as f:
    text2 = f.read()

text2 = text2.replace(
    '<tr style="background:#181b22;"><td>총 잔고${exwarn}</td><td><span style="font-size:155%;font-weight:bold">${usd(b.ex_balance)}</span></td></tr>',
    '<tr style="background:#181b22;"><td>초기 자본</td><td><span style="font-size:125%;font-weight:bold">${usd(b.seed)}</span></td></tr>\n     <tr style="background:#181b22;"><td>총 잔고${exwarn}</td><td><span style="font-size:155%;font-weight:bold">${usd(b.ex_balance)}</span></td></tr>'
)

with open("/Users/l/project/8888/index.html", "w") as f:
    f.write(text2)

