import re
path = '/Users/l/project/8888/app.py'
with open(path, 'r') as f: code = f.read()

# Update BOTS list
old_bots = """BOTS = [
    ("8401", 8401, "OKX"),    ("8402", 8402, "OKX"),
    ("8403", 8403, "OKX"),    
    ("8405", 8405, "OKX"),    
    ("8407", 8407, "BNC"),    ("8409", 8409, "BNC"),    ("8410", 8410, "BNC"),
]"""
new_bots = """BOTS = [
    ("8401", 8401, "OKX"),    ("8402", 8402, "OKX"),
    ("8403", 8403, "OKX"),    ("8404", 8404, "OKX"),
    ("8405", 8405, "OKX"),    ("8406", 8406, "OKX"),
    ("8407", 8407, "BNC"),    ("8408", 8408, "BNC"),
    ("8409", 8409, "BNC"),    ("8410", 8410, "BNC"),
]"""
if old_bots in code:
    code = code.replace(old_bots, new_bots)
else:
    print("Could not find old_bots in app.py")

# Update EXCLUDED_BOTS list
old_excluded = """EXCLUDED_BOTS = [
    ("8403", 8403, "OKX"),
    ("8404", 8404, "OKX"),
    ("8405", 8405, "OKX"),
    ("8406", 8406, "OKX"),
    ("8408", 8408, "BNC"),
]"""
new_excluded = """EXCLUDED_BOTS = [
    # No excluded bots
]"""
if old_excluded in code:
    code = code.replace(old_excluded, new_excluded)
else:
    print("Could not find old_excluded in app.py")

with open(path, 'w') as f: f.write(code)
