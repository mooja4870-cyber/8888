import re
path = '/Users/l/project/8888/send_discord_hourly_graph.py'
with open(path, 'r') as f:
    code = f.read()

# 1. Update GROUP_x_IDS definitions
old_groups = """GROUP_3_IDS = ["8407", "8408", "8409"]
GROUP_1_IDS = ["8401", "8402", "8410"]
GROUP_2_IDS = ["8403", "8404", "8405", "8406"]
GROUP_A_IDS = GROUP_3_IDS
ALL_BOT_IDS = ["8407", "8409", "8401", "8402", "8410", "8403", "8404", "8405", "8406"]"""

new_groups = """GROUP_1_IDS = ["8401", "8402", "8410"]
GROUP_2_IDS = ["8403", "8405", "8407", "8409"]
ALL_BOT_IDS = GROUP_1_IDS + GROUP_2_IDS"""

code = code.replace(old_groups, new_groups)

# 2. Update docstring
code = code.replace("- 그룹 A: 8402, 8404, 8405, 8409\n- 그룹 B: 8401, 8403, 8407, 8408\n- 그룹 C: 8403, 8408\n- 개별 봇: 8401, 8402, 8403, 8404, 8405, 8407, 8408, 8409", 
                   "- 그룹 1: 8401, 8402, 8410\n- 그룹 2: 8403, 8405, 8407, 8409\n- 개별 봇: 8401, 8402, 8403, 8405, 8407, 8409, 8410")


# 3. Update collect_hourly_data return signature
code = code.replace("group_3_series = []\n    group_1_series = []\n    group_2_series = []", "group_1_series = []\n    group_2_series = []")
code = code.replace("return timestamps, group_3_series, group_1_series, group_2_series, bot_series", "return timestamps, group_1_series, group_2_series, bot_series")

# 4. Remove group_3 calculation block
group_3_calc = """        # 그룹 3 (8407, 8408, 8409) 계산
        tot_seed_3 = sum(bot_seeds[bid] for bid in GROUP_3_IDS)
        avg_ret_3 = sum(bot_rets[bid] * bot_seeds[bid] for bid in GROUP_3_IDS) / tot_seed_3 if tot_seed_3 else 0.0
        group_3_series.append(round(avg_ret_3, 2))

"""
code = code.replace(group_3_calc, "")

# 5. send_report updates
old_send = """    timestamps, series_3, series_1, series_2, bot_series = collect_hourly_data(num_hours=40)
    
    # 1) 그룹별 추이 리포트 (그룹 3: 8407, 8408, 8409 / 그룹 1: 8401, 8402, 8410 / 그룹 2: 8403, 8404)
    graph_3 = generate_ascii_graph("그룹3(" + ", ".join(GROUP_3_IDS) + ") 봇 집계", series_3, is_group=True)
    graph_1 = generate_ascii_graph("그룹1(" + ", ".join(GROUP_1_IDS) + ") 봇 집계", series_1, is_group=True)
    graph_2 = generate_ascii_graph("그룹2(" + ", ".join(GROUP_2_IDS) + ") 봇 집계", series_2, is_group=True)
    
    msg_groups = (
        f"📢 **[8888 봇 그룹별 40시간 일평균수익률 추이 리포트]**\\n"
        f"📅 **집계 시각**: `{now_str}` (최근 40시간 정시 추이)\\n"
        f"--------------------------------------------------\\n"
        f"{graph_3}\\n"
        f"--------------------------------------------------\\n"
        f"{graph_1}\\n"
        f"--------------------------------------------------\\n"
        f"{graph_2}\\n"
        f"--------------------------------------------------\\n"
    )"""

new_send = """    timestamps, series_1, series_2, bot_series = collect_hourly_data(num_hours=40)
    
    # 1) 그룹별 추이 리포트 (그룹 1: 8401, 8402, 8410 / 그룹 2: 8403, 8405, 8407, 8409)
    graph_1 = generate_ascii_graph("그룹1(" + ", ".join(GROUP_1_IDS) + ") 봇 집계", series_1, is_group=True)
    graph_2 = generate_ascii_graph("그룹2(" + ", ".join(GROUP_2_IDS) + ") 봇 집계", series_2, is_group=True)
    
    msg_groups = (
        f"📢 **[8888 봇 그룹별 40시간 일평균수익률 추이 리포트]**\\n"
        f"📅 **집계 시각**: `{now_str}` (최근 40시간 정시 추이)\\n"
        f"--------------------------------------------------\\n"
        f"{graph_1}\\n"
        f"--------------------------------------------------\\n"
        f"{graph_2}\\n"
        f"--------------------------------------------------\\n"
    )"""

code = code.replace(old_send, new_send)

with open(path, 'w') as f:
    f.write(code)

print("send_discord_hourly_graph.py done")
