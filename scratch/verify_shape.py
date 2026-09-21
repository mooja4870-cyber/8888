import json
import time

# Let's check a sample of app.py's calc_bot_metrics logic directly
seed = 10.0
days = 22.0

asset_values = [11.0, 11.5, 10.5, 12.0, 12.5]
for i, asset in enumerate(asset_values):
    cum_ret = (asset - seed) / seed * 100
    cur_days = days + (i * (300/86400))
    daily_ret = cum_ret / cur_days
    print(f"Asset: {asset:.2f}, DailyRet: {daily_ret:.4f}%")
