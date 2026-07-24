#!/usr/bin/env python3
"""
8개 봇 (8401~8409) 통합 및 봇별 구간(1h, 4h, 12h, 24h) 승패 및 PnL 디스코드 웹훅 알림 스크립트.
- 매 정시 (00분 00초) 자동 발송 스케줄러 포함.
"""
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

WEBHOOK_URL = "https://discord.com/api/webhooks/1479512076585144372/gOAz4w-a8htQvE0a92CZCMItHdeaGucSXe_4yWirbQYzXAjI_VorbjlI2JjzYXpJlGZy"
ROOT_DIR = "/Users/l/project"
BOTS = [
    ("8401", "8401_OKX"),
    ("8402", "8402_OKX"),
    ("8403", "8403_OKX"),
    ("8404", "8404_OKX"),
    ("8405", "8405_OKX"),
    ("8407", "8407_BNC"),
    ("8408", "8408_BNC"),
    ("8409", "8409_BNC"),
]

INTERVALS = [
    ("1h", 3600, "1시간"),
    ("4h", 14400, "4시간"),
    ("12h", 43200, "12시간"),
    ("24h", 86400, "24시간"),
]


def collect_stats():
    now_ts = time.time()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    overall = {key: {"win": 0, "loss": 0, "draw": 0, "pnl": 0.0} for key, _, _ in INTERVALS}
    by_bot = {bot_id: {key: {"win": 0, "loss": 0, "draw": 0, "pnl": 0.0} for key, _, _ in INTERVALS} for bot_id, _ in BOTS}

    for bot_id, name in BOTS:
        csv_path = os.path.join(ROOT_DIR, bot_id, "data", "trade_history.csv")
        if not os.path.exists(csv_path):
            continue

        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # '청산' 유형만 체결 승패 집계
                    trade_type = row.get("유형") or row.get("type") or ""
                    if trade_type != "청산" and trade_type != "close":
                        continue

                    t_str = row.get("시간") or row.get("exit_time") or row.get("timestamp") or ""
                    pnl_str = row.get("수익(USDT)") or row.get("pnl") or row.get("realized_pnl") or "0"

                    if not t_str:
                        continue

                    try:
                        pnl = float(pnl_str)
                    except ValueError:
                        pnl = 0.0

                    try:
                        dt = datetime.strptime(t_str[:19], "%Y-%m-%d %H:%M:%S")
                        row_ts = dt.timestamp()
                    except ValueError:
                        continue

                    age = now_ts - row_ts
                    for key, sec, _ in INTERVALS:
                        if age <= sec:
                            if pnl > 0:
                                by_bot[bot_id][key]["win"] += 1
                                overall[key]["win"] += 1
                            elif pnl < 0:
                                by_bot[bot_id][key]["loss"] += 1
                                overall[key]["loss"] += 1
                            else:
                                by_bot[bot_id][key]["draw"] += 1
                                overall[key]["draw"] += 1

                            by_bot[bot_id][key]["pnl"] += pnl
        except Exception as e:
            print(f"[{bot_id}] CSV 읽기 예외: {e}", flush=True)

    return now_str, overall, by_bot


def format_rate(win, loss):
    total = win + loss
    if total == 0:
        return 0.0
    return (win / total) * 100.0


def build_discord_messages(now_str, overall, by_bot):
    # Message 1: Overall Summary + Bots 8401~8404
    # Message 2: Bots 8405~8409 (디스코드 메시지 길이 제한 2000자 초과 방지)

    # 1. Overall Section
    ov_lines = [
        f"📢 **[8개 봇 통합 & 봇별 구간 승패 리포트]**",
        f"📅 **집계 시각**: `{now_str}`",
        f"--------------------------------------------------",
        f"🌐 **[전체 8개 봇 종합 성과]**",
    ]
    for key, _, label in INTERVALS:
        w = overall[key]["win"]
        l = overall[key]["loss"]
        d = overall[key]["draw"]
        pnl = overall[key]["pnl"]
        rate = format_rate(w, l)
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        ov_lines.append(f"⏱️ **{label:>4}** | 거래 {w+l+d:2d}건 ({w:2d}승 {l:2d}패, {rate:5.1f}%) | PnL: `{pnl_str}`")

    ov_lines.append(f"--------------------------------------------------")
    ov_lines.append(f"🤖 **[봇별 4개 구간 승패 상세 기록]**")

    # Split bots into two batches
    batch1 = BOTS[:4]
    batch2 = BOTS[4:]

    msg1_lines = list(ov_lines)
    for bot_id, name in batch1:
        msg1_lines.append(f"🔹 **[{name}]**")
        for key, _, label in INTERVALS:
            b_w = by_bot[bot_id][key]["win"]
            b_l = by_bot[bot_id][key]["loss"]
            b_pnl = by_bot[bot_id][key]["pnl"]
            b_rate = format_rate(b_w, b_l)
            p_str = f"+${b_pnl:.2f}" if b_pnl >= 0 else f"-${abs(b_pnl):.2f}"
            msg1_lines.append(f"   • {label:>4}: {b_w}승 {b_l}패 ({b_rate:5.1f}%) | PnL: `{p_str}`")

    msg2_lines = []
    for bot_id, name in batch2:
        msg2_lines.append(f"🔹 **[{name}]**")
        for key, _, label in INTERVALS:
            b_w = by_bot[bot_id][key]["win"]
            b_l = by_bot[bot_id][key]["loss"]
            b_pnl = by_bot[bot_id][key]["pnl"]
            b_rate = format_rate(b_w, b_l)
            p_str = f"+${b_pnl:.2f}" if b_pnl >= 0 else f"-${abs(b_pnl):.2f}"
            msg2_lines.append(f"   • {label:>4}: {b_w}승 {b_l}패 ({b_rate:5.1f}%) | PnL: `{p_str}`")

    msg2_lines.append("--------------------------------------------------")
    msg2_lines.append("🔗 *8888 관제 시스템 정시(00분00초) 자동 리포트*\n=================================\n=================================")

    return "\n".join(msg1_lines), "\n".join(msg2_lines)


def send_webhook(content):
    payload = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.getcode()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 디스코드 전송 결과: HTTP {status}", flush=True)
            return status in (200, 204)
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 디스코드 전송 실패: {e}", flush=True)
        return False


def run_once():
    now_str, overall, by_bot = collect_stats()
    msg1, msg2 = build_discord_messages(now_str, overall, by_bot)
    s1 = send_webhook(msg1)
    time.sleep(1)
    s2 = send_webhook(msg2)
    return s1 and s2


def loop_hourly():
    print("🚀 매 정시(00분 00초) 디스코드 리포트 스케줄러 시작...", flush=True)
    # 1회 즉시 발송
    run_once()

    while True:
        # 다음 정시 00분 00초까지 남은 초 계산
        now = datetime.now()
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        sleep_sec = (next_hour - now).total_seconds()

        print(f"⏳ 다음 정시 발송 시각: {next_hour.strftime('%H:%M:%S')} ({int(sleep_sec)}초 후)", flush=True)
        time.sleep(sleep_sec)

        print(f"⏰ 정시 (00분 00초) 달성! 디스코드 리포트 발송 중...", flush=True)
        run_once()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        loop_hourly()
    else:
        run_once()
