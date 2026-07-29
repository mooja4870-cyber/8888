with open('/Users/l/project/8405/core/engine.py', 'r') as f:
    lines = f.readlines()

for i, line in enumerate(lines[658:715]):
    print(f"{i + 659}: {line.rstrip()}")
