#!/usr/bin/env python3
"""
8888 그룹별 최근 30시간 일평균수익률 추이 아스키 그래프 디스코드 웹훅 알림 스크립트.
- 그룹 A: 8401, 8402, 8404, 8408
- 그룹 B: 8403, 8405, 8407, 8409
- 매시 00분 00초 정시 자동 발송 스케줄러 포함.
"""
import os
import sys
import csv
import json
import time
import urllib.request
from datetime import datetime, timedelta

WEBHOOK_URL = "https://discord.com/api/webhooks/1479512076585144372/gOAz4w-a8htQvE0a92CZCMItHdeaGucSXe_4yWirbQYzXAjI_VorbjlI2JjzYXpJlGZy"
ROOT_DIR = "/Users/l/project"
SNAP_FILE = os.path.join(ROOT_DIR, "8888", "snapshots.json")

GROUP_A_IDS = ["8401", "8402", "8404", "8408"]
GROUP_B_IDS = ["8403", "8405", "8407", "8409"]

BOT_FOLDERS = {
    "8401": "8401",
    "8402": "8402",
    "8403": "8403",
    "8404": "8404",
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

def collect_hourly_data(num_hours=30):
    now = time.time()
    lt = time.localtime(now)
    # 정시 기준 timestamp 30개 (과거 -> 현재 순)
    sec_into = lt.tm_min * 60 + lt.tm_sec
    latest_top_of_hour = int(now - sec_into)
    
    timestamps = [latest_top_of_hour - 3600 * (num_hours - 1 - i) for i in range(num_hours)]
    
    # 봇별 이력 미리 로드
    bot_data = {bid: load_bot_history(bid) for bid in (GROUP_A_IDS + GROUP_B_IDS)}
    
    # snapshots.json 참조 (실측치 우선 적용)
    snap_map = {}
    if os.path.exists(SNAP_FILE):
        try:
            with open(SNAP_FILE, "r", encoding="utf-8") as f:
                snaps = json.load(f)
                for s in snaps:
                    ts_str = s.get("ts", "")
                    if ts_str.endswith(":00"):
                        snap_map[ts_str] = s.get("bots", {})
        except Exception:
            pass

    group_a_series = []
    group_b_series = []
    
    for T in timestamps:
        ts_key = time.strftime("%Y-%m-%d %H:00", time.localtime(T))
        
        # 그룹 A 계산
        rets_a = []
        seeds_a = []
        for bid in GROUP_A_IDS:
            seed, perf, exits = bot_data[bid]
            # snapshot에 정보가 있고 해당 값 활용 가능한 경우
            d_ret = calculate_bot_daily_ret_at(seed, perf, exits, T)
            rets_a.append(d_ret)
            seeds_a.append(seed)
            
        tot_seed_a = sum(seeds_a)
        avg_ret_a = sum(r * s for r, s in zip(rets_a, seeds_a)) / tot_seed_a if tot_seed_a else 0.0
        group_a_series.append(round(avg_ret_a, 2))

        # 그룹 B 계산
        rets_b = []
        seeds_b = []
        for bid in GROUP_B_IDS:
            seed, perf, exits = bot_data[bid]
            d_ret = calculate_bot_daily_ret_at(seed, perf, exits, T)
            rets_b.append(d_ret)
            seeds_b.append(seed)
            
        tot_seed_b = sum(seeds_b)
        avg_ret_b = sum(r * s for r, s in zip(rets_b, seeds_b)) / tot_seed_b if tot_seed_b else 0.0
        group_b_series.append(round(avg_ret_b, 2))

    return timestamps, group_a_series, group_b_series

def generate_ascii_graph(title: str, bot_ids: list, values: list) -> str:
    if not values:
        return f"{title}\n(데이터 없음)"
        
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
        
    bot_names = ", ".join(bot_ids)
    lines = []
    lines.append(f"📊 **[{bot_names} 봇 집계] {title}** (최신: `{values[-1]:+.2f}%`) ")
    lines.append("```")
    for r in range(height):
        row_str = "".join(grid[r])
        if r == 0:
            lines.append(f"{max_v:6.2f}|{row_str}")
        elif r == height - 1:
            lines.append(f"{min_v:6.2f}|{row_str}")
        else:
            lines.append(f"      |{row_str}")
    lines.append("```")
    return "\n".join(lines)

def post_to_discord(content: str):
    data = {"content": content}
    json_data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json_data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200 or resp.status == 244 or resp.status == 204
    except Exception as e:
        print(f"[DISCORD POST ERROR] {e}", flush=True)
        return False

def send_report():
    now_str = datetime.now().strftime("%Y-%m-%d %H:00:00")
    timestamps, series_a, series_b = collect_hourly_data(num_hours=30)
    
    graph_a = generate_ascii_graph("30시간 일평균수익률 추이(%)", GROUP_A_IDS, series_a)
    graph_b = generate_ascii_graph("30시간 일평균수익률 추이(%)", GROUP_B_IDS, series_b)
    
    message = (
        f"📢 **[8888 봇 그룹별 30시간 일평균수익률 추이 리포트]**\n"
        f"📅 **집계 시각**: `{now_str}` (최근 30시간 정시 추이)\n"
        f"--------------------------------------------------\n"
        f"{graph_a}\n\n"
        f"{graph_b}\n"
        f"--------------------------------------------------"
    )
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Discord 리포트 발송 시도...")
    ok = post_to_discord(message)
    if ok:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Discord 발송 성공!")
    else:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Discord 발송 실패.")
    return ok

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        send_report()
        return

    print("🚀 [Discord 30시간 일평균수익률 추이 그래프 발송 스케줄러 가동 중]", flush=True)
    send_report()  # 시작 시 1회 발송
    
    while True:
        now = time.time()
        # 다음 정시 (00분 00초) 시점 계산
        dt = datetime.fromtimestamp(now)
        next_hour = (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        sleep_sec = (next_hour - datetime.now()).total_seconds()
        
        if sleep_sec > 0:
            print(f"⏱️ 다음 발송까지 대기: {sleep_sec:.1f}초 ({next_hour.strftime('%H:%M:%S')})", flush=True)
            time.sleep(sleep_sec)
            
        send_report()

if __name__ == "__main__":
    main()
