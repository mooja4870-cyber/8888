import os
import glob

target_dir = "/Users/l/project/8888"
files_to_check = glob.glob(os.path.join(target_dir, "*.py"))

search_1 = '["8401", "8402", "8407", "8409", "8410"]'
replace_1 = '["8401", "8402", "8407", "8409", "8410"]'

search_2 = '{"8401", "8402", "8407", "8409", "8410"}'
replace_2 = '{"8401", "8402", "8407", "8409", "8410"}'

for filepath in files_to_check:
    with open(filepath, 'r') as f:
        content = f.read()
    
    if search_1 in content or search_2 in content:
        new_content = content.replace(search_1, replace_1).replace(search_2, replace_2)
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"Updated {os.path.basename(filepath)}")

print("Done.")
