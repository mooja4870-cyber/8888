import json

def patch_bot(bot_id, is_8402=False):
    path = f"/Users/l/project/{bot_id}/config.json"
    with open(path, 'r') as f:
        cfg = json.load(f)
    
    if not is_8402:
        if 'DON_SL_ATR_MULT' in cfg: cfg['DON_SL_ATR_MULT'] = 2.0
        if 'DON_TP_ATR_MULT' in cfg: cfg['DON_TP_ATR_MULT'] = 3.0
        if 'GLOBAL_SL_PCT' in cfg: cfg['GLOBAL_SL_PCT'] = 1.2
        if 'GLOBAL_TP_PCT' in cfg: cfg['GLOBAL_TP_PCT'] = 2.5
    else:
        # For 8402, SL is already 1.5. TP is 5.0.
        if 'DON_TP_ATR_MULT' in cfg: cfg['DON_TP_ATR_MULT'] = 3.0
        
    cfg['USE_TRAILING_STOP'] = True
    cfg['USE_PARTIAL_TP'] = True
    
    # ensure reasonable parameters if not set
    if cfg.get('TRAILING_ACTIVATE_PCT') is None: cfg['TRAILING_ACTIVATE_PCT'] = 0.015
    if cfg.get('TRAILING_CALLBACK_PCT') is None: cfg['TRAILING_CALLBACK_PCT'] = 0.005
    if cfg.get('PARTIAL_TP_TRIGGER_PCT') is None: cfg['PARTIAL_TP_TRIGGER_PCT'] = 0.012
    if cfg.get('PARTIAL_TP_FRACTION') is None: cfg['PARTIAL_TP_FRACTION'] = 0.5
    
    with open(path, 'w') as f:
        json.dump(cfg, f, indent=4)
    print(f"{bot_id} config.json patched!")

patch_bot('8402', is_8402=True)
patch_bot('8403')
patch_bot('8405')
