import re

with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix hist_metrics
hist_metrics_pattern = re.compile(
    r'def hist_metrics\(path, perf_start\):.*?(?=def drawdown_metrics)',
    re.DOTALL
)

hist_metrics_replacement = """def hist_metrics(path, perf_start):
    \"\"\"봇 대시보드와 동일하게 trade_history.csv에서 당일/누적 지표 재계산.
    - 금일 실현 손익 = Σ(청산 수익), 경계 = max(오늘 00:00 KST, perf_start). 행 단위 합산.
    - 당일/누적 주문·승률 = order_id별로 묶어 합산 > 0 승 / < 0 패 (봇 방식).
    - 24시간 내 진입 수 = 현재 시각 기준 직전 24시간 롤링 윈도우 내 진입 기록 수 (청산 무관).
    \"\"\"
    today0 = time.strftime("%Y-%m-%d 00:00:00")
    ps = (perf_start or "")[:19]
    b_today = max(today0, ps) if ps else today0
    b_since = ps or today0
    exits = _load_exits(path)
    entries = _load_entries(path)

    today_pnl = 0.0
    today_grp, since_grp = {}, {}
    for i, (ts, pnl, oid) in enumerate(exits):
        if ts >= b_since:
            key = oid if oid else f"no_id_{i}"
            since_grp[key] = since_grp.get(key, 0.0) + pnl
            if ts >= b_today:
                today_pnl += pnl
                today_grp[key] = today_grp.get(key, 0.0) + pnl

    tw = sum(1 for v in today_grp.values() if v > 0)
    tl = sum(1 for v in today_grp.values() if v < 0)
    sw = sum(1 for v in since_grp.values() if v > 0)
    sl = sum(1 for v in since_grp.values() if v < 0)

    # 봇 효율 지표
    wins = [v for v in since_grp.values() if v > 0]
    losses = [abs(v) for v in since_grp.values() if v < 0]
    gross_win, gross_loss = sum(wins), sum(losses)
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None
    avg_wl = None
    if wins and losses:
        avg_wl = round((gross_win / len(wins)) / (gross_loss / len(losses)), 2)
    n_grp = len(since_grp)
    expectancy = round(sum(since_grp.values()) / n_grp, 4) if n_grp else None

    # 기간별 진입 수 (롤링 윈도우 + perf_start + oid 중복 제거)
    now = time.time()
    periods = {"1h": 3600, "6h": 21600, "12h": 43200, "24h": 86400,
               "48h": 172800, "72h": 259200, "1w": 604800}
    entries_by_period = {}
    for key, secs in periods.items():
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - secs))
        if ps and ps > cutoff:
            cutoff = ps
        
        unique_entries = set()
        for i, (ts, oid) in enumerate(entries):
            if ts >= cutoff:
                if oid:
                    unique_entries.add(oid)
                else:
                    unique_entries.add(f"no_id_{i}")
        entries_by_period[key] = len(unique_entries)

    return {"today_pnl": round(today_pnl, 4), "today_w": tw, "today_l": tl,
            "since_w": sw, "since_l": sl, "since_orders": sw + sl,
            "profit_factor": profit_factor, "avg_wl": avg_wl, "expectancy": expectancy,
            "entries_24h": entries_by_period["24h"], "entries_by_period": entries_by_period}

"""

# Fix drawdown_metrics
drawdown_metrics_pattern = re.compile(
    r'def drawdown_metrics\(path, perf_start, seed\):.*?(?=def heatmap_grid)',
    re.DOTALL
)

drawdown_metrics_replacement = """def drawdown_metrics(path, perf_start, seed):
    \"\"\"[2단계] 실현손익 equity curve로 최대낙폭(누적)·당일낙폭 계산 (seed 대비 %).\"\"\"
    if not seed or seed <= 0:
        return {"max_dd": None, "today_dd": None}
    ps = (perf_start or "")[:19]
    today0 = time.strftime("%Y-%m-%d 00:00:00")
    
    raw_exits = sorted(_load_exits(path))
    grp = {}
    for i, (ts, pnl, oid) in enumerate(raw_exits):
        key = oid if oid else f"no_id_{i}"
        if key not in grp:
            grp[key] = {"ts": ts, "pnl": 0.0}
        grp[key]["pnl"] += pnl
    
    exits = sorted([(v["ts"], v["pnl"], k) for k, v in grp.items()])

    eq = peak = seed
    max_dd = 0.0
    eq_at_today_start = seed
    for ts, pnl, oid in exits:
        if ps and ts < ps:
            continue
        if ts < today0:
            eq_at_today_start = eq + pnl
        eq += pnl
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    eqt = peak_t = eq_at_today_start
    today_dd = 0.0
    for ts, pnl, oid in exits:
        if ps and ts < ps:
            continue
        if ts < today0:
            continue
        eqt += pnl
        if eqt > peak_t:
            peak_t = eqt
        dd = (eqt - peak_t) / peak_t * 100
        if dd < today_dd:
            today_dd = dd

    return {"max_dd": round(max_dd, 2), "today_dd": round(today_dd, 2)}

"""

# Fix heatmap_grid
heatmap_grid_pattern = re.compile(
    r'def heatmap_grid\(path, perf_start, days=7\):.*?(?=# ── 거래소 조회 전용 클라이언트)',
    re.DOTALL
)

heatmap_grid_replacement = """def heatmap_grid(path, perf_start, days=7):
    \"\"\"[3단계] 최근 N일 청산 실현손익을 요일×시간대(6시간 4구간)로 집계.
    반환: {"wday_bucket": pnl_sum, ...}  (wday 0=월 … 6=일, bucket 0=00–06 … 3=18–24)
    \"\"\"
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days * 86400))
    if perf_start:
        ps = perf_start[:19]
        if ps > cutoff:
            cutoff = ps
    grid = {}
    for ts, pnl, oid in _load_exits(path):
        if ts < cutoff:
            continue
        try:
            st = time.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        key = "%d_%d" % (st.tm_wday, st.tm_hour // 6)
        grid[key] = grid.get(key, 0.0) + pnl
    return grid


"""

content = hist_metrics_pattern.sub(hist_metrics_replacement, content)
content = drawdown_metrics_pattern.sub(drawdown_metrics_replacement, content)
content = heatmap_grid_pattern.sub(heatmap_grid_replacement, content)

with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
