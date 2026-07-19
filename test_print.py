import app
import discord_alert
data = app.collect()
prev_total, prev_bots, history, prev_sub_total = discord_alert._load_state(discord_alert.STATE_FILE)
# Subset calculation (8402, 8407, 8409)
subset_names = {"8402", "8407", "8409"}
sub_assets = 0.0
sub_seed = 0.0
sub_bots = []
for b in data.get("bots", []):
    if str(b.get("name")) in subset_names:
        sub_bots.append(b)
        bal = b.get("ex_balance") if (b.get("ex_ok") and b.get("ex_balance") is not None) else ((b.get("seed") or 0) + (b.get("total") or 0))
        bseed = b.get("seed") if b.get("seed") else bal
        sub_assets += bal
        sub_seed += bseed

sub_days = max([app.bot_days(b["perf_start"]) for b in sub_bots] or [1.0])
sub_cum_ret = round((sub_assets - sub_seed) / sub_seed * 100, 2) if sub_seed else None
sub_total = round(sub_cum_ret / sub_days, 2) if sub_cum_ret is not None else None
msg = discord_alert.build_message(data, prev_total, prev_bots, history, "", sub_assets, sub_total, prev_sub_total)
print(msg)
