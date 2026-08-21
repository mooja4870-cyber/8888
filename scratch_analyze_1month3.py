import sys, json, os, datetime

bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
start_dt = "2026-07-05 00:00:00"

results = []
days = (datetime.datetime.now() - datetime.datetime.strptime(start_dt, '%Y-%m-%d %H:%M:%S')).total_seconds() / 86400

for b in bots:
    bot_dir = f"/Users/l/project/{b}"
    if not os.path.exists(bot_dir): continue
    
    seed = 10.0
    try:
        with open(f"{bot_dir}/data/stats.json") as f:
            st = json.load(f)
            seed = st.get('seed_usdt', 10.0)
    except: pass
    
    csv_path = f"{bot_dir}/data/trade_history.csv"
    if not os.path.exists(csv_path): continue
    
    pnl = 0.0
    w_sun = 0; l_sun = 0
    w_yeok = 0; l_yeok = 0
    closed = []
    
    with open(csv_path) as f:
        headers = f.readline().strip().split(",")
        try:
            pnl_idx = headers.index("수익(USDT)") if "수익(USDT)" in headers else headers.index("pnl_usdt")
            dt_idx = headers.index("시간") if "시간" in headers else headers.index("close_dt")
            mode_idx = headers.index("매매모드") if "매매모드" in headers else headers.index("trade_mode")
        except ValueError as e:
            continue
            
        for line in f:
            parts = line.strip().split(",")
            if len(parts) <= max(pnl_idx, dt_idx, mode_idx): continue
            close_dt = parts[dt_idx]
            if close_dt >= start_dt:
                try:
                    p = float(parts[pnl_idx])
                except:
                    continue
                mode = parts[mode_idx]
                closed.append({"pnl": p, "mode": mode, "dt": close_dt})
                pnl += p
                if p > 0:
                    if mode == "역방향": w_yeok += 1
                    else: w_sun += 1
                elif p < 0:
                    if mode == "역방향": l_yeok += 1
                    else: l_sun += 1
                    
    closed.sort(key=lambda x: x["dt"])
    seq = "".join(["O" if c["pnl"] > 0 else "x" for c in closed[-30:]])
    
    ret_pct = (pnl / seed * 100) if seed > 0 else 0
    
    # Calculate days based on actual first trade if available
    first_dt = datetime.datetime.now()
    if closed:
        first_dt = datetime.datetime.strptime(closed[0]["dt"][:19], '%Y-%m-%d %H:%M:%S')
    
    actual_days = (datetime.datetime.now() - first_dt).total_seconds() / 86400
    if actual_days < 1: actual_days = 1.0 # prevent div by zero
    
    daily_ret = ret_pct / actual_days if actual_days > 0 else 0
    w = w_sun + w_yeok
    l = l_sun + l_yeok
    
    results.append({
        "bot": b,
        "seed": seed,
        "pnl": pnl,
        "ret_pct": ret_pct,
        "daily_ret": daily_ret,
        "actual_days": actual_days,
        "w": w, "l": l,
        "w_yeok": w_yeok, "l_yeok": l_yeok,
        "w_sun": w_sun, "l_sun": l_sun,
        "seq": seq
    })

results.sort(key=lambda x: x['daily_ret'], reverse=True)

print(f"=== 최근 1개월 (2026-07-05 ~ 현재) 수익률 정리 ===")
total_pnl = sum(r['pnl'] for r in results)
total_seed = sum(r['seed'] for r in results)
total_ret = (total_pnl / total_seed * 100) if total_seed > 0 else 0
print(f"전체 원금: ${total_seed:.2f}, 전체 수익: ${total_pnl:.2f}, 총수익률: {total_ret:+.2f}%")
print("-" * 50)
for r in results:
    w = r['w']; l = r['l']
    tot = w+l
    print(f"봇 {r['bot']} | {r['actual_days']:.1f}일 가동 | 총 {tot}전 {w}승 {l}패 (순 {r['w_sun']}승/역 {r['w_yeok']}승)")
    print(f"  수익: ${r['pnl']:+.2f} ({r['ret_pct']:+.2f}%) | 일평균: {r['daily_ret']:+.2f}%")
    print(f"  최근30: {r['seq']}")
    print("-" * 50)
