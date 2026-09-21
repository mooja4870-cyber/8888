import re
path = '/Users/l/project/8888/send_discord_stats.py'
with open(path, 'r') as f:
    code = f.read()

# Replace Groups
old_groups = """GROUP_3_BOTS = [
    ("8407", "8407_BNC"),
    ("8408", "8408_BNC"),
    ("8409", "8409_BNC"),
]
GROUP_1_BOTS = [
    ("8401", "8401_OKX"),
    ("8402", "8402_OKX"),
    ("8410", "8410_BNC"),
]
GROUP_2_BOTS = [
    ("8403", "8403_OKX"),
    ("8404", "8404_OKX"),
    ("8405", "8405_OKX"),
    ("8406", "8406_OKX"),
]"""

new_groups = """GROUP_1_BOTS = [
    ("8401", "8401_OKX"),
    ("8402", "8402_OKX"),
    ("8410", "8410_BNC"),
]
GROUP_2_BOTS = [
    ("8403", "8403_OKX"),
    ("8405", "8405_OKX"),
    ("8407", "8407_BNC"),
    ("8409", "8409_BNC"),
]"""

code = code.replace(old_groups, new_groups)

# Remove Group 3 printing logic
old_g3_print = """    lines.append("--------------------------------------------------")
    lines.append("🔗 *8888 관제 시스템 정시(00분00초) 자동 리포트*\\n=================================\\n=================================")

    lines.append(f"🤖 **[그룹3 (8407, 8408, 8409) 봇별 4개 구간 승패 상세]**")
    for bot_id, name in GROUP_3_BOTS:
        is_bf = bot_modes.get(bot_id, False)
        mode_tag = "**[역]** 🐸 역방향(청개구리)" if is_bf else "**[순]** 🎯 순방향(정방향)"
        lines.append(f"🔹 **[{name}]** {mode_tag}")
        for key, _, label in INTERVALS:
            b_w = by_bot[bot_id][key]["win"]
            b_l = by_bot[bot_id][key]["loss"]
            b_pnl = by_bot[bot_id][key]["pnl"]
            b_rate = format_rate(b_w, b_l)
            p_str = f"+${b_pnl:.2f}" if b_pnl >= 0 else f"-${abs(b_pnl):.2f}"
            lines.append(f"   • {label:>4}: {b_w}승 {b_l}패 ({b_rate:5.1f}%) | PnL: `{p_str}`")
        raw_seq = bot_seq.get(bot_id, "")
        seq_grouped = " ".join([raw_seq[i:i+5] for i in range(0, len(raw_seq), 5)])
        if seq_grouped:
            lines.append(f"   • 승패흐름: {seq_grouped}")"""

new_g3_print = """    lines.append("--------------------------------------------------")
    lines.append("🔗 *8888 관제 시스템 정시(00분00초) 자동 리포트*\\n=================================\\n=================================")"""

code = code.replace(old_g3_print, new_g3_print)

# Update Group 2 printing header
code = code.replace("🤖 **[그룹2 (8403, 8404, 8405, 8406) 봇별 4개 구간 승패 상세]**", "🤖 **[그룹2 (8403, 8405, 8407, 8409) 봇별 4개 구간 승패 상세]**")

with open(path, 'w') as f:
    f.write(code)

print("send_discord_stats.py done")
