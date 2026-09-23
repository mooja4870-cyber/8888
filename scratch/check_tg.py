import os

for i in range(8401, 8411):
    env_path = f"/Users/l/project/{i}/.env"
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()
            token = ""
            chat_id = ""
            for line in lines:
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.strip().split("=")[1]
                if line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.strip().split("=")[1]
            print(f"[{i}] TOKEN: {token[-5:] if token else 'None'} | CHAT_ID: {chat_id}")
