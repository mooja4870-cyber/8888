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

    # ⚠️ 부분청산 처리: 같은 order_id의 모든 청산을 합산한 후 승패 판정
    def _order_id(r):
        return r.get('order_id') or r.get('trade_id') or ''

    def _group_by_order(rows):
        """order_id별 손익 합산. (order_id → 총손익) 딕셔너리 반환"""
        grouped = {}
        for r in rows:
            oid = _order_id(r)
            if not oid:
                # order_id 없으면 해당 행을 단독 거래로 처리
                oid = f"_uniq_{len(grouped)}"
            pnl = float(r.get('pnl_usdt') or 0.0)
            grouped[oid] = grouped.get(oid, 0.0) + pnl
        return grouped

    # today stats
    today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_closed = [r for r in closed if _exit_dt(r) >= today_start]
    today_pnl = sum([float(r.get('pnl_usdt') or 0.0) for r in today_closed])

    today_grouped = _group_by_order(today_closed)
    today_w = sum(1 for pnl in today_grouped.values() if pnl > 0)
    today_l = sum(1 for pnl in today_grouped.values() if pnl < 0)

    # since stats
    since_grouped = _group_by_order(closed)
    since_w = sum(1 for pnl in since_grouped.values() if pnl > 0)
    since_l = sum(1 for pnl in since_grouped.values() if pnl < 0)
    since_orders = len(since_grouped)

    # sequence and 20 stats for discord alert
    # 주의: closed는 이미 시간순으로 정렬됨 (과거→최신)
    # order_id별로 그룹화한 후 시간순 정렬 (마지막 청산 시각 기준)
    order_id_to_rows = {}
    for r in closed:
        oid = _order_id(r)
        if not oid:
            oid = f"_uniq_{len(order_id_to_rows)}"
        if oid not in order_id_to_rows:
            order_id_to_rows[oid] = []
        order_id_to_rows[oid].append(r)

    grouped_trades = []  # (exit_time, pnl, trade_mode)
    for oid, rows in order_id_to_rows.items():
        pnl = sum(float(r.get('pnl_usdt') or 0.0) for r in rows)
        exit_time = max(_exit_dt(r) for r in rows)
        # trade_mode는 첫 진입 기준 (rows 중 가장 오래된 exit_time을 찾음)
        first_row = min(rows, key=_exit_dt)
        trade_mode = first_row.get('trade_mode', '')
        grouped_trades.append((exit_time, pnl, trade_mode))

    grouped_trades.sort(key=lambda x: x[0])  # 시간순 정렬 (과거→최신)

    # 최근 30개 거래의 승패 시퀀스 (최신이 꼬리)
    recent_30_trades = grouped_trades[-30:]
    seq = ""
    for exit_time, pnl, trade_mode in reversed(recent_30_trades):
        seq += "O" if pnl > 0 else "x"

    # 최근 20개 거래 중 순/역 비중
    last_20_trades = grouped_trades[-20:]
    sun20_cnt = sum(1 for _, _, mode in last_20_trades if mode != '역방향')
    yeok20_cnt = sum(1 for _, _, mode in last_20_trades if mode == '역방향')
    
    # 순방향/역방향 분류 (order_id별 그룹의 trade_mode는 첫 진입 기준)
    sun_grouped = {}  # order_id → 총손익 (순방향만)
    yeok_grouped = {} # order_id → 총손익 (역방향만)
    for r in closed:
        oid = _order_id(r)
        if not oid:
            oid = f"_uniq_{len(sun_grouped) + len(yeok_grouped)}"
        pnl = float(r.get('pnl_usdt') or 0.0)
        if r.get('trade_mode') == '역방향':
            yeok_grouped[oid] = yeok_grouped.get(oid, 0.0) + pnl
        else:
            sun_grouped[oid] = sun_grouped.get(oid, 0.0) + pnl

    since_w_sun = sum(1 for pnl in sun_grouped.values() if pnl > 0)
    since_l_sun = sum(1 for pnl in sun_grouped.values() if pnl < 0)
    since_w_yeok = sum(1 for pnl in yeok_grouped.values() if pnl > 0)
    since_l_yeok = sum(1 for pnl in yeok_grouped.values() if pnl < 0)

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
