import json

path = '/Users/l/project/8410/config.json'
with open(path, 'r') as f:
    cfg = json.load(f)

# Revert widened stops
cfg['ATR_SL_MULT'] = 1.5
cfg['ATR_TP_MULT'] = 3.0
cfg['DON_SL_ATR_MULT'] = 2.0
# Keep DON_TP_ATR_MULT at 4.0 or change it? Let's leave at 4.0 but rely on trailing/partial.

# Enable trailing stop
cfg['USE_TRAILING_STOP'] = True

# Enable Partial TP
cfg['USE_PARTIAL_TP'] = True

with open(path, 'w') as f:
    json.dump(cfg, f, indent=4)
print("config.json patched!")
