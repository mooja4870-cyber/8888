import json, os

bots = ['8402', '8403', '8405']
for b in bots:
    state_file = f"/Users/l/project/{b}/app_state.json"
    config_file = f"/Users/l/project/{b}/config.json"
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
            win = state.get('WIN_COUNT', 0)
            loss = state.get('LOSS_COUNT', 0)
            profit = state.get('TOTAL_PROFIT_USDT', 0)
            print(f"[{b}] W/L: {win}W/{loss}L, Profit: {profit:.2f}")
    if os.path.exists(config_file):
        with open(config_file) as f:
            cfg = json.load(f)
            print(f"  -> DON_SL: {cfg.get('DON_SL_ATR_MULT')}, DON_TP: {cfg.get('DON_TP_ATR_MULT')}")
            print(f"  -> GLOBAL_SL: {cfg.get('GLOBAL_SL_PCT')}, GLOBAL_TP: {cfg.get('GLOBAL_TP_PCT')}")
            print(f"  -> TRAILING: {cfg.get('USE_TRAILING_STOP')}, PARTIAL: {cfg.get('USE_PARTIAL_TP')}")
            print(f"  -> SCALEOUT: {cfg.get('USE_SCALEOUT')}")
