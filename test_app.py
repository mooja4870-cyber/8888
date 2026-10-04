from app import read_bot_config

cfg_8401 = read_bot_config("8401")
print("8401 SL:", cfg_8401["stop_loss_pct"])
print("8401 Strategy:", cfg_8401["strategy"])

cfg_8407 = read_bot_config("8407")
print("8407 SL:", cfg_8407["stop_loss_pct"])
print("8407 Strategy:", cfg_8407["strategy"])
