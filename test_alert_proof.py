import sys; sys.path.insert(0, '/Users/l/project/8888')
import app
import discord_alert
from unittest.mock import patch
import time

data = app.collect()
prev_total, prev_bots, history, prev_sub_total, series, asset_history, asset_series = discord_alert._load_state(discord_alert.STATE_FILE)

orig_localtime = time.localtime
def get_mocked_localtime(minute):
    def mocked(*args):
        t = orig_localtime(*args)
        return time.struct_time((t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, minute, t.tm_sec, t.tm_wday, t.tm_yday, t.tm_isdst))
    return mocked

with patch('discord_alert.time.localtime', side_effect=get_mocked_localtime(39)):
    msg_39 = discord_alert.build_message(data, prev_total, prev_bots, history, '그룹 1 테스트')

with patch('discord_alert.time.localtime', side_effect=get_mocked_localtime(40)):
    msg_40 = discord_alert.build_message(data, prev_total, prev_bots, history, '그룹 1 테스트')

print("=== 1분 마다 (39분 예시) ===")
print('\n'.join(msg_39.split('\n')[2:8]))
print("\n=== 5분 마다 (40분 예시) ===")
print('\n'.join(msg_40.split('\n')[2:8]))
