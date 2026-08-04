import sys, json, os, datetime

# Suppress stdout to avoid any debug prints from history_helper.py
old_stdout = sys.stdout
sys.stdout = open(os.devnull, 'w')

try:
    bot_folder = sys.argv[1]
    perf_start = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else ""

    sys.path.insert(0, bot_folder)
    os.chdir(bot_folder)

    from core.history_helper import load_local_trade_history, closed_trades_since

    trades = load_local_trade_history()
    dt = datetime.datetime.strptime(perf_start[:19], '%Y-%m-%d %H:%M:%S') if perf_start else None
    closed = closed_trades_since(trades, dt)
    closed.sort(key=lambda x: x.get('close_dt', ''))

    # today stats
    today_str = datetime.datetime.now().strftime("%Y-%m-%d 00:00:00")
    today_closed = [r for r in closed if r.get('close_dt', '') >= today_str]
    today_pnl = sum([float(r.get('pnl_usdt') or 0.0) for r in today_closed])
    today_w = sum(1 for r in today_closed if float(r.get('pnl_usdt') or 0.0) > 0)
    today_l = sum(1 for r in today_closed if float(r.get('pnl_usdt') or 0.0) < 0)

    # since stats
    since_w = sum(1 for r in closed if float(r.get('pnl_usdt') or 0.0) > 0)
    since_l = sum(1 for r in closed if float(r.get('pnl_usdt') or 0.0) < 0)
    since_orders = len(closed)

    # sequence and 20 stats for discord alert
    recent_30 = closed[-30:]
    last_20 = closed[-20:]

    seq = ""
    for r in recent_30:
        pnl = float(r.get('pnl_usdt') or 0.0)
        seq += "O" if pnl > 0 else "x"

    sun20_cnt = sum(1 for r in last_20 if r.get('trade_mode') != '역방향')
    yeok20_cnt = sum(1 for r in last_20 if r.get('trade_mode') == '역방향')
    
    since_w_sun = sum(1 for r in closed if float(r.get('pnl_usdt') or 0.0) > 0 and r.get('trade_mode') != '역방향')
    since_l_sun = sum(1 for r in closed if float(r.get('pnl_usdt') or 0.0) < 0 and r.get('trade_mode') != '역방향')
    since_w_yeok = sum(1 for r in closed if float(r.get('pnl_usdt') or 0.0) > 0 and r.get('trade_mode') == '역방향')
    since_l_yeok = sum(1 for r in closed if float(r.get('pnl_usdt') or 0.0) < 0 and r.get('trade_mode') == '역방향')

    out = {
        "today_pnl": round(today_pnl, 4),
        "today_w": today_w,
        "today_l": today_l,
        "since_w": since_w,
        "since_l": since_l,
        "since_orders": since_orders,
        "since_w_sun": since_w_sun,
        "since_l_sun": since_l_sun,
        "since_w_yeok": since_w_yeok,
        "since_l_yeok": since_l_yeok,
        "seq": seq,
        "sun20": sun20_cnt,
        "yeok20": yeok20_cnt
    }
    
    # Restore stdout and print json
    sys.stdout = old_stdout
    print(json.dumps(out))
except Exception as e:
    sys.stdout = old_stdout
    print(json.dumps({"error": str(e)}))
