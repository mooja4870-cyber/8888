import os, re
BASE_DIR = "/Users/l/project"
BOTS = ["8401", "8402", "8403", "8404", "8405", "8408", "8410"]
error_patterns = set()
for bot in BOTS:
    bot_path = os.path.join(BASE_DIR, bot)
    for root, dirs, files in os.walk(bot_path):
        for file in files:
            if file.endswith(".py") and not file.startswith("."):
                try:
                    with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                        content = f.read()
                        matches = re.findall(r'(?:logger\.error|logger\.warning|logger\.critical|Exception|ValueError|log)\s*\(\s*[f]?["\'](.*?)["\']', content)
                        for m in matches:
                            clean_m = re.sub(r'\{.*?\}', '', m).strip()
                            if len(clean_m) > 3:
                                error_patterns.add(clean_m)
                except:
                    pass
with open("/Users/l/project/8888/error_dict.txt", "w", encoding="utf-8") as f:
    for ep in error_patterns:
        f.write(ep + "\n")
print(f"Dumped {len(error_patterns)} patterns.")
