#!/usr/bin/env python3
"""
8888 그룹별 및 8개 개별 봇 30시간 일평균수익률 추이 아스키 그래프 디스코드 웹훅 알림 스크립트.
- 그룹 A: 8402, 8404, 8405, 8409
- 그룹 B: 8401, 8403, 8407, 8408
- 그룹 C: 8403, 8408
- 개별 봇: 8401, 8402, 8403, 8404, 8405, 8407, 8408, 8409
- 매시 00분 00초 정시 자동 발송 스케줄러 포함.
"""
import os
import sys
import csv
import json
import time
import urllib.request
from datetime import datetime, timedelta

WEBHOOK_URL = ""  # 알림 중단
ROOT_DIR = "/Users/l/project"
SNAP_FILE = os.path.join(ROOT_DIR, "8888", "snapshots.json")

GROUP_A_IDS = ["8401", "8402", "8403", "8408", "8409"]
ALL_BOT_IDS = ["8401", "8402", "8403", "8408", "8409"]

BOT_FOLDERS = {
    "8401": "8401",
    "8402": "8402",
    "8403": "8403",
    "8405": "8405",
    "8407": "8407",
    "8408": "8408",
    "8409": "8409",
}

def epoch(ts_str):
    try:
        return time.mktime(time.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None

def load_bot_history(bot_id):
    """(seed, perf_epoch, [(exit_epoch, pnl), ...])"""
    folder = BOT_FOLDERS.get(bot_id, bot_id)
    d = os.path.join(ROOT_DIR, folder, "data")
    seed = 10.0
    perf = None
    try:
        stats_path = os.path.join(d, "stats.json")
        if os.path.exists(stats_path):
            with open(stats_path, "r", encoding="utf-8") as f:
                s = json.load(f)
                seed = float(s.get("seed_money", 10.0) or 10.0)
                perf = epoch(s.get("perf_start_time") or "")
    except Exception:
        pass
    
    exits = []
    try:
        hist_path = os.path.join(d, "trade_history.csv")
        if os.path.exists(hist_path):
            with open(hist_path, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.reader(f)
                for r in reader:
                    if len(r) < 7 or r[2] != "청산":
                        continue
                    e = epoch(r[0].strip())
                    if e is None:
                        continue
                    try:
                        exits.append((e, float(r[6])))
                    except Exception:
                        continue
    except Exception:
        pass
        
    exits.sort()
    return seed, perf, exits

def calculate_bot_daily_ret_at(seed, perf, exits, T):
    if not seed or not perf or T < perf:
        return 0.0
    cum = sum(p for e, p in exits if perf <= e <= T)
    cum_ret = (cum / seed) * 100.0
    days = max(1.0, (T - perf) / 86400.0)
    return round(cum_ret / days, 2)

def collect_hourly_data(num_hours=40):
    now = time.time()
    lt = time.localtime(now)
    sec_into = lt.tm_min * 60 + lt.tm_sec
    latest_top_of_hour = int(now - sec_into)
    
    timestamps = [latest_top_of_hour - 3600 * (num_hours - 1 - i) for i in range(num_hours)]
    bot_data = {bid: load_bot_history(bid) for bid in ALL_BOT_IDS}
    
    group_a_series = []
    group_b_series = []
    group_c_series = []
    bot_series = {bid: [] for bid in ALL_BOT_IDS}
    
    for T in timestamps:
        # 봇별 수치 계산
        bot_rets = {}
        bot_seeds = {}
        for bid in ALL_BOT_IDS:
            seed, perf, exits = bot_data[bid]
            d_ret = calculate_bot_daily_ret_at(seed, perf, exits, T)
            bot_rets[bid] = d_ret
            bot_seeds[bid] = seed
            bot_series[bid].append(d_ret)
            
        # 그룹 A (통합그룹) 계산
        tot_seed_a = sum(bot_seeds[bid] for bid in GROUP_A_IDS)
        avg_ret_a = sum(bot_rets[bid] * bot_seeds[bid] for bid in GROUP_A_IDS) / tot_seed_a if tot_seed_a else 0.0
        group_a_series.append(round(avg_ret_a, 2))

    return timestamps, group_a_series, bot_series

def get_bot_recent_sequence(bid: str) -> str:
    try:
        import app
        path = f"/Users/l/project/{bid}/data/trade_history.csv"
        if not os.path.exists(path):
            return ""
        exits = app._load_exits(path)
        
        stats_path = f"/Users/l/project/{bid}/data/stats.json"
        perf_start = ""
        if os.path.exists(stats_path):
            with open(stats_path, "r", encoding="utf-8") as f:
                s = json.load(f)
                perf_start = (s.get("perf_start_time") or "").replace("T", " ")[:19]
        if perf_start:
            exits = [e for e in exits if e[0] >= perf_start]
            
        grp = {}
        ts_map = {}
        for ts, pnl, oid in exits:
            if oid:
                grp[oid] = grp.get(oid, 0.0) + pnl
                ts_map[oid] = max(ts_map.get(oid, ""), ts)
                
        filtered_oids = [o for o in grp.keys() if round(grp[o], 4) != 0.0]
        # 종전 reverse=True(최신이 왼쪽)는 알림 본문의 시퀀스(과거→최신)와 방향이 정반대여서
        # 같은 화면의 두 시퀀스가 서로 다르게 읽혔다. 좌→우 시간 진행으로 통일한다.
        sorted_oids = sorted(filtered_oids, key=lambda o: ts_map[o])
        recent_oids = sorted_oids[-40:]
        
        seq = ""
        for oid in recent_oids:
            seq += "O" if grp[oid] > 0 else "x"
        return " ".join([seq[i:i+5] for i in range(0, len(seq), 5)])
    except Exception:
        return ""

def generate_ascii_graph(label: str, values: list, is_group: bool = False, seq_str: str = "") -> str:
    if not values:
        return f"{label}\n(데이터 없음)"
        
    n = len(values)
    min_v = min(values)
    max_v = max(values)
    
    if abs(max_v - min_v) < 1e-4:
        min_v -= 0.1
        max_v += 0.1

    height = 5
    grid = [[" " for _ in range(n)] for _ in range(height)]
    
    for x, v in enumerate(values):
        norm = (v - min_v) / (max_v - min_v)
        y = int(round((1.0 - norm) * (height - 1)))
        y = max(0, min(height - 1, y))
        grid[y][x] = "•"
        
    icon = "📊" if is_group else "🤖"
    lines = []
    seq_suffix = f"\n`{seq_str}`" if seq_str else ""
    lines.append(f"{icon} **[{label}]** (최신: `{values[-1]:+.2f}%`){seq_suffix}")
    lines.append("```")
    for r in range(height):
        row_str = "".join(grid[r])
        lines.append(row_str)
    lines.append("```")
    return "\n".join(lines)

def post_to_discord(content: str):
    if not WEBHOOK_URL:
        print("[DISCORD POST] WEBHOOK_URL 미설정 (알림 중단 상태)", flush=True)
        return False
    data = {"content": content}
    json_data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json_data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204, 244)
    except Exception as e:
        print(f"[DISCORD POST ERROR] {e}", flush=True)
        return False

def send_report():
    now_str = datetime.now().strftime("%Y-%m-%d %H:00:00")
    timestamps, series_a, bot_series = collect_hourly_data(num_hours=40)
    
    # 1) 그룹 메시지
    graph_a = generate_ascii_graph("통합그룹(" + ", ".join(GROUP_A_IDS) + ") 전체 봇 집계", series_a, is_group=True)
    
    msg_groups = (
        f"📢 **[8888 봇 통합그룹 40시간 일평균수익률 추이 리포트]**\n"
        f"📅 **집계 시각**: `{now_str}` (최근 40시간 정시 추이)\n"
        f"--------------------------------------------------\n"
        f"{graph_a}\n"
        f"--------------------------------------------------"
    )
    
    # 2) 개별 봇 Part 1 (통합그룹: 8401, 8402, 8403, 8408, 8409)
    part1_bots = ["8401", "8402", "8403", "8408", "8409"]
    graphs_part1 = [generate_ascii_graph(f"{bid} 봇", bot_series[bid], is_group=False, seq_str=get_bot_recent_sequence(bid)) for bid in part1_bots]
    msg_part1 = (
        f"🤖 **[통합그룹 (8401,2,3,8,9) 40시간 일평균수익률 추이 리포트]**\n"
        f"--------------------------------------------------\n"
        + "\n\n".join(graphs_part1) + "\n"
        f"--------------------------------------------------"
    )

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Discord 2개 분할 리포트 발송 시도...", flush=True)
    ok1 = post_to_discord(msg_groups)
    time.sleep(0.5)
    ok2 = post_to_discord(msg_part1)
    if ok1 and ok2:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Discord 2개 리포트 모두 발송 성공!", flush=True)
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 일부 리포트 발송 실패.", flush=True)

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        send_report()
        return

    print("🚀 [Discord 8개 봇 통합 & 개별 30시간 일평균수익률 추이 스케줄러 가동 중]", flush=True)
    send_report()  # 시작 시 1회 발송
    
    while True:
        now = time.time()
        dt = datetime.fromtimestamp(now)
        next_hour = (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        sleep_sec = (next_hour - datetime.now()).total_seconds()
        
        if sleep_sec > 0:
            print(f"⏱️ 다음 발송까지 대기: {sleep_sec:.1f}초 ({next_hour.strftime('%H:%M:%S')})", flush=True)
            time.sleep(sleep_sec)
            
        send_report()

if __name__ == "__main__":
    main()
