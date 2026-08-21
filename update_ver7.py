import sys

path = "/Users/l/project/8888/ver.md"
with open(path, "r") as f:
    content = f.read()

content = content.replace("## v2.3.14", "## v2.3.15")

with open(path, "w") as f:
    f.write(content)
