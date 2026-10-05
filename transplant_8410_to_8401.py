import os
import shutil

src = "/Users/l/project/8410"
dst = "/Users/l/project/8401"

# 1. 삭제할 항목 (뇌와 껍데기)
to_delete = ["core", "ui", "app.py", "bot.py", "config.json"]

for item in to_delete:
    target_path = os.path.join(dst, item)
    if os.path.exists(target_path):
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
        else:
            os.remove(target_path)

# 2. 복사할 항목 (소스에서 타겟으로)
for item in to_delete:
    src_path = os.path.join(src, item)
    dst_path = os.path.join(dst, item)
    if os.path.exists(src_path):
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path)
        else:
            shutil.copy2(src_path, dst_path)

print(f"Transplant from {src} to {dst} is ready.")
