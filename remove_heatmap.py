with open("dashboard.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

out = []
skip = False
for i, line in enumerate(lines):
    if "── [3단계] 시간대별 성과 히트맵" in line:
        skip = True
    
    if skip and "document.getElementById('heatmapTable').innerHTML=hmTable;" in line:
        skip = False
        continue
    
    if not skip:
        out.append(line)

with open("dashboard.html", "w", encoding="utf-8") as f:
    f.writelines(out)

print("Heatmap JS block removed.")
