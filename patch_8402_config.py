import json

config_path = '/Users/l/project/8402/config.json'

with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

# Make the changes
config['USE_SCALEOUT'] = False
config['DON_SL_ATR_MULT'] = 1.5
config['DON_TP_ATR_MULT'] = 5.0

with open(config_path, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=4, ensure_ascii=False)

print("Patch applied to 8402 config.json")
