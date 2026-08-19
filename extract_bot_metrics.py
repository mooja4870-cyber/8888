import sys, json, os, datetime

# Suppress stdout to avoid any debug prints from history_helper.py
old_stdout = sys.stdout
sys.stdout = open(os.devnull, 'w')

try:
    bot_folder = sys.argv[1]
    perf_start = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else ""

    sys.path.insert(0, bot_folder)
    os.chdir(bot_folder)

    from core.history_helper import load_local_trade_history, closed_trades_since, _row_to_trade, _dedupe_trades
    import pandas as pd

    trades = load_local_trade_history()
    
    # 만약 최근 trade_history.csv 가 리셋/정리되어 건수가 부족하면 .bak 파일 등 과거 이력도 함께 로드
    if len(trades) < 40:
        for extra in ['trade_history.csv.bak', 'trade_history_before_cleanup.csv']:
            ep = os.path.join(bot_folder, 'data', extra)
            if os.path.exists(ep) and os.path.getsize(ep) > 10:
                try:
                    df = pd.read_csv(ep, encoding='utf-8-sig')
                    df.columns = [c.strip() for c in df.columns]
                    for _, row in df.iterrows():
                        t = _row_to_trade(row)
                        if t:
                            trades.append(t)
                except Exception:
                    pass
        trades = _dedupe_trades(trades)

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

    # 초기화 시점 이후 집계
    closed = closed_trades_since(trades, dt)
    # 전체 누적 청산 내역 (최근 30건 승패 시퀀스용)
    all_closed = closed_trades_since(trades, None)

    # closed_trades_since()가 돌려주는 청산시각 키는 'exit_time'(pandas Timestamp)이다.
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
    all_closed.sort(key=_exit_dt)

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

    # sequence and 20 stats for discord alert — 최근 30건 승패 시퀀스 (최신이 왼쪽)
    # closed가 30건 이상이면 closed 기준, 30건 미만이면 all_closed 기준으로 최근 30건 확보
    seq_target = closed if len(closed) >= 30 else all_closed
    recent_30 = seq_target[-30:]
    last_20 = seq_target[-20:]

    seq = ""
    for r in reversed(recent_30):
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
