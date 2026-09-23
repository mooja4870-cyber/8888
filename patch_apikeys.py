import os
import shutil

unified_api_keys = """
import os
import logging
import json

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_MD_PATH = os.path.join(_ROOT, "api.md")
CONFIG_PATH = os.path.join(_ROOT, "config.json")

def _get_exchange_id():
    try:
        with open(CONFIG_PATH, 'r') as f:
            cfg = json.load(f)
            return str(cfg.get('EXCHANGE_ID', 'binance')).lower()
    except:
        return 'binance'

_EXCHANGE = _get_exchange_id()

_KEY_MAP = {
    "apikey": f"{_EXCHANGE.upper()}_API_KEY",
    "secretkey": f"{_EXCHANGE.upper()}_SECRET_KEY",
    "passphrase": f"{_EXCHANGE.upper()}_PASSPHRASE",
    "binance_api_key": "BINANCE_API_KEY",
    "binance_secret_key": "BINANCE_SECRET_KEY",
    "binance_passphrase": "BINANCE_PASSPHRASE",
    "okx_api_key": "OKX_API_KEY",
    "okx_secret_key": "OKX_SECRET_KEY",
    "okx_passphrase": "OKX_PASSPHRASE",
}

def _clean(value: str) -> str:
    return value.strip().strip('"').strip("'").strip()

def load_api_keys(path: str = API_MD_PATH, override: bool = True) -> bool:
    try:
        if not os.path.exists(path):
            logger.warning(f"[API_KEYS] api.md 없음: {path}")
            return False

        found = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if "=" not in s:
                    continue
                raw_key, _, raw_val = s.partition("=")
                k = raw_key.strip().lower().replace(" ", "")
                env_name = _KEY_MAP.get(k)
                if env_name and env_name not in found:
                    val = _clean(raw_val)
                    if val:
                        found[env_name] = val

        for env_name, val in found.items():
            if override or not os.getenv(env_name):
                os.environ[env_name] = val

        # 필수 키 체크
        prefix = _EXCHANGE.upper()
        required = (f"{prefix}_API_KEY", f"{prefix}_SECRET_KEY")
        ok = all(os.getenv(e) for e in required)
        if ok:
            logger.info(f"[API_KEYS] api.md 키 주입 완료 (apikey …{found.get(required[0],'')[-4:]})")
        else:
            missing = [e for e in required if not os.getenv(e)]
            logger.warning(f"[API_KEYS] api.md 키 일부 누락: {missing}")
        return ok
    except Exception as e:
        logger.error(f"[API_KEYS] api.md 로드 실패: {e}")
        return False
"""

for target in ["8404", "8406", "8408"]:
    print(f"▶ Patching API Keys for {target} ...")
    
    # 1. Create core/api_keys.py
    api_keys_path = f"/Users/l/project/{target}/core/api_keys.py"
    with open(api_keys_path, "w") as f:
        f.write(unified_api_keys.strip() + "\n")
        
    # 2. Inject into app.py
    app_path = f"/Users/l/project/{target}/app.py"
    with open(app_path, "r") as f:
        app_content = f.read()
    
    if "load_api_keys()" not in app_content:
        # load_dotenv(override=True) 밑에 주입
        if "load_dotenv(override=True)" in app_content:
            app_content = app_content.replace(
                "load_dotenv(override=True)",
                "load_dotenv(override=True)\nfrom core.api_keys import load_api_keys\nload_api_keys()"
            )
        else:
            app_content = app_content.replace(
                "load_dotenv()",
                "load_dotenv()\nfrom core.api_keys import load_api_keys\nload_api_keys()"
            )
        with open(app_path, "w") as f:
            f.write(app_content)
            
    # 3. Inject into bot.py
    bot_path = f"/Users/l/project/{target}/bot.py"
    with open(bot_path, "r") as f:
        bot_content = f.read()
        
    if "load_api_keys()" not in bot_content:
        # load_dotenv(override=True) 밑에 주입
        if "load_dotenv(override=True)" in bot_content:
            bot_content = bot_content.replace(
                "load_dotenv(override=True)",
                "load_dotenv(override=True)\nfrom core.api_keys import load_api_keys\nload_api_keys()"
            )
        else:
            bot_content = bot_content.replace(
                "load_dotenv()",
                "load_dotenv()\nfrom core.api_keys import load_api_keys\nload_api_keys()"
            )
        with open(bot_path, "w") as f:
            f.write(bot_content)

print("✅ Patch applied successfully.")
