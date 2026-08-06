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
    dt = None
    if perf_start:
        ps_str = perf_start[:19].replace('T', ' ')
        if len(ps_str) == 10:
            ps_str += " 00:00:00"
        elif len(ps_str) == 16:
            ps_str += ":00"
        try:
            dt = datetime.datetime.strptime(ps_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass
    closed = closed_trades_since(trades, dt)

    # closed_trades_since()가 돌려주는 청산시각 키는 'exit_time'(pandas Timestamp)이다.
    # 종전엔 존재하지 않는 'close_dt'를 참조해 기본값 ''만 돌아왔고, 그 결과
    #   ① 정렬이 전량 동일 키('')로 무효화되어 승패 시퀀스가 시간순이 아니었으며
    #   ② 오늘 필터('' >= '2026-..')가 항상 False라 today_w/today_l이 늘 0이었다.
    def _exit_dt(r):
        et = r.get('exit_time')
        if et is None:
            return datetime.datetime.min
        try:
            et = et.to_pydatetime()          # pandas Timestamp
        except AttributeError:
            pass
        if isinstance(et, str):
            try:
                et = datetime.datetime.strptime(et[:19], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return datetime.datetime.min
        try:
            return et.replace(tzinfo=None)
        except Exception:
            return datetime.datetime.min

    closed.sort(key=_exit_dt)                 # 과거 → 최신

    # today stats
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_closed = [r for r in closed if _exit_dt(r) >= today_start]
    today_pnl = sum([float(r.get('pnl_usdt') or 0.0) for r in today_closed])
    today_w = sum(1 for r in today_closed if float(r.get('pnl_usdt') or 0.0) > 0)
    today_l = sum(1 for r in today_closed if float(r.get('pnl_usdt') or 0.0) < 0)

    # since stats
    since_w = sum(1 for r in closed if float(r.get('pnl_usdt') or 0.0) > 0)
    since_l = sum(1 for r in closed if float(r.get('pnl_usdt') or 0.0) < 0)
    since_orders = len(closed)

    # sequence and 20 stats for discord alert — 정렬이 과거→최신이므로 꼬리가 최근분
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
