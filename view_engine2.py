with open('/Users/l/project/8405/core/engine.py', 'r') as f:
    lines = f.readlines()

for i, line in enumerate(lines[730:745]):
    print(f"{i + 731}: {line.rstrip()}")
