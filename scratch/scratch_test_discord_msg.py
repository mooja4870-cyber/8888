import send_discord_stats
now_str, overall, by_bot, bot_modes, bot_seq = send_discord_stats.collect_stats()
msg1, msg2 = send_discord_stats.build_discord_messages(now_str, overall, by_bot, bot_modes, bot_seq)
print(msg1)
print(msg2)
