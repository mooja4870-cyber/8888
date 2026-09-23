import re
path = '/Users/l/project/8888/app.py'
with open(path, 'r') as f: code = f.read()

code = code.replace(
    'target_bots = ["8401", "8402", "8403", "8405", "8407", "8409", "8410"]',
    'target_bots = ["8401", "8402", "8403", "8404", "8405", "8406", "8407", "8408", "8409", "8410"]'
)

with open(path, 'w') as f: f.write(code)
