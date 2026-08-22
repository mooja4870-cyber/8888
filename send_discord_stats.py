#!/usr/bin/env python3
"""
8개 봇 (8401~8409) 통합 및 봇별 구간(1h, 4h, 12h, 24h) 승패 및 매매방향([순]/[역]) 디스코드 웹훅 알림 스크립트.
- 매 정시 (00분 00초) 자동 발송 스케줄러 포함.
"""
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

WEBHOOK_URL = ""  # 알림 중단
ROOT_DIR = "/Users/l/project"
BOTS = [
    ("8401", "8401_OKX"),
    ("8402", "8402_OKX"),
    ("8403", "8403_OKX"),
    ("8408", "8408_BNC"),
    ("8409", "8409_BNC"),
]

INTERVALS = [
    ("1h", 3600, "1시간"),
    ("4h", 14400, "4시간"),
    ("12h", 43200, "12시간"),
    ("24h", 86400, "24시간"),
]


def load_bot_modes():
    modes = {}
    for bot_id, name in BOTS:
        cfg_path = os.path.join(ROOT_DIR, bot_id, "config.json")
        is_bf = False
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    is_bf = bool(cfg.get("USE_BLUEFROG", False))
            except Exception:
                pass
        modes[bot_id] = is_bf
    return modes


def collect_stats():
    now_ts = time.time()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    overall = {key: {"win": 0, "loss": 0, "draw": 0, "pnl": 0.0} for key, _, _ in INTERVALS}
    by_bot = {bot_id: {key: {"win": 0, "loss": 0, "draw": 0, "pnl": 0.0} for key, _, _ in INTERVALS} for bot_id, _ in BOTS}
    bot_seq = {bot_id: "" for bot_id, _ in BOTS}
    bot_modes = load_bot_modes()

    for bot_id, name in BOTS:
        csv_path = os.path.join(ROOT_DIR, bot_id, "data", "trade_history.csv")
        if not os.path.exists(csv_path):
            continue

        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                all_pnls = []

                for row in reader:
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
                    
                    all_pnls.append(pnl)

                # Generate sequence string from last 30 trades
                recent = all_pnls[-30:]
                seq_str = "".join(["O" if p > 0 else "x" for p in recent])
                bot_seq[bot_id] = seq_str

        except Exception as e:
            print(f"[{bot_id}] CSV 읽기 예외: {e}", flush=True)

    return now_str, overall, by_bot, bot_modes, bot_seq


def format_rate(win, loss):
    total = win + loss
    if total == 0:
        return 0.0
    return (win / total) * 100.0


def build_discord_messages(now_str, overall, by_bot, bot_modes, bot_seq):
    lines = []
    lines.append(f"📊 **정시 자동 리포트 종합 통계**")
    lines.append(f"🕒 기준: {now_str}")
    lines.append(f"--------------------------------------------------")
    
    # [순]/[역] 전체 카운트
    pure_cnt, frog_cnt = 0, 0
    for bot_id, name in BOTS:
        is_bf = bot_modes.get(bot_id, False)
        if is_bf:
            frog_cnt += 1
            lines.append(f"• `{name}` | **[역]** 🐸 역방향 (원천: 🎯순방향)")
        else:
            pure_cnt += 1
            lines.append(f"• `{name}` | **[순]** 🎯 순방향 (원천: 🎯순방향)")

    lines.append(f"💡 **요약**: 🎯 **[순]** 순방향: `{pure_cnt}개` | 🐸 **[역]** 역방향(청개구리): `{frog_cnt}개`")
    lines.append(f"--------------------------------------------------")
    lines.append(f"🌐 **[전체 {len(BOTS)}개 봇 종합 성과]**")

    for key, _, label in INTERVALS:
        w = overall[key]["win"]
        l = overall[key]["loss"]
        d = overall[key]["draw"]
        pnl = overall[key]["pnl"]
        rate = format_rate(w, l)
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        lines.append(f"⏱️ **{label:>4}** | 거래 {w+l+d:2d}건 ({w:2d}승 {l:2d}패, {rate:5.1f}%) | PnL: `{pnl_str}`")

    lines.append(f"--------------------------------------------------")
    lines.append(f"🤖 **[통합그룹 (8401,3,8,9) 봇별 4개 구간 승패 상세]**")

    for bot_id, name in BOTS:
        is_bf = bot_modes.get(bot_id, False)
        mode_tag = "**[역]** 🐸 역방향(청개구리)" if is_bf else "**[순]** 🎯 순방향(정방향)"
        lines.append(f"🔹 **[{name}]** {mode_tag}")
        for key, _, label in INTERVALS:
            b_w = by_bot[bot_id][key]["win"]
            b_l = by_bot[bot_id][key]["loss"]
            b_pnl = by_bot[bot_id][key]["pnl"]
            b_rate = format_rate(b_w, b_l)
            p_str = f"+${b_pnl:.2f}" if b_pnl >= 0 else f"-${abs(b_pnl):.2f}"
            lines.append(f"   • {label:>4}: {b_w}승 {b_l}패 ({b_rate:5.1f}%) | PnL: `{p_str}`")
        raw_seq = bot_seq.get(bot_id, "")
        seq_grouped = " ".join([raw_seq[i:i+5] for i in range(0, len(raw_seq), 5)])
        if seq_grouped:
            lines.append(f"   • 승패흐름: {seq_grouped}")

    lines.append("--------------------------------------------------")
    lines.append("🔗 *8888 관제 시스템 정시(00분00초) 자동 리포트*\n=================================\n=================================")

    return "\n".join(lines)


def send_webhook(content):
    if not WEBHOOK_URL:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] WEBHOOK_URL 미설정 (알림 중단 상태)", flush=True)
        return False
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
    now_str, overall, by_bot, bot_modes, bot_seq = collect_stats()
    msg = build_discord_messages(now_str, overall, by_bot, bot_modes, bot_seq)
    s1 = send_webhook(msg)
    return s1


def loop_hourly():
    print("🚀 매 정시(00분 00초) 디스코드 리포트 스케줄러 시작...", flush=True)
    run_once()

    while True:
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
