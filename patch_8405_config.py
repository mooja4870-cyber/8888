import re

filepath = "/Users/l/project/8405/core/config.py"
with open(filepath, "r") as f:
    content = f.read()

content = re.sub(r'USE_REGIME_ROUTER:\s*bool\s*=\s*True', 'USE_REGIME_ROUTER: bool = False', content)

with open(filepath, "w") as f:
    f.write(content)
    
print("8405 config patched.")
