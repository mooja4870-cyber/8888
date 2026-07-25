#!/usr/bin/env python3
"""
8개 봇 (8401~8409) 매매방향 자동 스위칭(최근 5전 3패 이상 시 반전) 
최근 24시간 실적 점검 및 알고리즘 정밀 검증 스크립트
"""
import os
import sys
import glob
import json
import csv
from datetime import datetime, timedelta

BASE_DIR = "/Users/l/project"
BOTS = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
NOW = datetime.now()
HOURS_24_AGO = NOW - timedelta(hours=24)

print(f"=== [8개 봇 5전 3패 자동 스위칭 최근 24시간 실적 및 로직 전수 점검] ===")
print(f"점검 시각: {NOW.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"대상 기간: {HOURS_24_AGO.strftime('%Y-%m-%d %H:%M:%S')} ~ {NOW.strftime('%Y-%m-%d %H:%M:%S')}\n")

report = {}

for bot in BOTS:
    bot_dir = os.path.join(BASE_DIR, bot)
    engine_file = os.path.join(bot_dir, "core", "engine.py")
    history_file = os.path.join(bot_dir, "trade_history.csv")
    log_file = os.path.join(bot_dir, "bot_engine.log")
    
    # 1. 코드 상 logic 검증
    code_ok = False
    if os.path.exists(engine_file):
        with open(engine_file, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
            if "closed_trades[:5]" in code and "losses >= 3" in code:
                code_ok = True
    
    # 2. 거래 이력 수집 및 시뮬레이션
    trades = []
    if os.path.exists(history_file):
        try:
            from core.history_helper import load_local_trade_history, aggregate_and_pair_trades
            # sys.path 조정
            sys.path.insert(0, bot_dir)
            raw = load_local_trade_history(history_file) if hasattr(load_local_trade_history, '__code__') and load_local_trade_history.__code__.co_argcount > 0 else []
            # 일반적인 csv 읽기 대안
        except Exception:
            pass

        # 직접 CSV 파싱 (안전성 확보)
        try:
            with open(history_file, "r", encoding="utf-8-sig", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # status or action or side
                    # 청산 거래 추적: exit_time 또는 timestamp
                    status = row.get("status") or row.get("state") or ""
                    pnl = float(row.get("pnl_usdt") or row.get("pnl") or row.get("realized_pnl") or 0.0)
                    dt_str = row.get("exit_time") or row.get("timestamp") or row.get("date") or ""
                    
                    # 간단 청산 판정
                    if "청산" in status or "CLOSED" in status.upper() or pnl != 0.0:
                        trades.append({
                            "raw_time": dt_str,
                            "pnl": pnl,
                            "symbol": row.get("symbol") or row.get("pair") or "",
                            "side": row.get("side") or row.get("direction") or "",
                        })
        except Exception as e:
            pass

    # 3. history_helper 사용 가능한 경우 실제 engine과 동일한 파싱 진행
    try:
        if bot_dir not in sys.path:
            sys.path.insert(0, bot_dir)
        import importlib
        # 동적 모듈 로드
        hh_spec = importlib.util.spec_from_file_location(f"hh_{bot}", os.path.join(bot_dir, "core", "history_helper.py"))
        hh = importlib.util.module_from_spec(hh_spec)
        hh_spec.loader.exec_module(hh)
        
        raw_trades = hh.load_local_trade_history()
        paired = hh.aggregate_and_pair_trades(raw_trades)
        closed_trades = [x for x in paired if x.get("status") == "청산 완료" and x.get("exit_time") is not None]
        # exit_time 오름차순 정렬하여 시간 순서대로 롤링 시뮬레이션
        closed_trades.sort(key=lambda x: str(x.get("exit_time")))
    except Exception as e:
        closed_trades = []

    # 최근 24시간 이내 청산된 거래
    recent_24h_closed = []
    for t in closed_trades:
        ex_time_str = str(t.get("exit_time"))
        # str to datetime 파싱
        dt_val = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                dt_val = datetime.strptime(ex_time_str.split(".")[0].replace("T", " "), "%Y-%m-%d %H:%M:%S")
                break
            except Exception:
                pass
        if dt_val and dt_val >= HOURS_24_AGO:
            recent_24h_closed.append((dt_val, t))

    # 4. 24시간 동안 롤링 시뮬레이션 (매 청산 시점마다 past 5개 확인)
    trigger_events = []
    for i in range(len(closed_trades)):
        # i 번째 거래가 청산되었을 때 당시의 최근 5건 (i번째 포함 과거 5건)
        if i < 4:
            continue
        window_5 = closed_trades[max(0, i-4):i+1] # 5건
        window_5_desc = sorted(window_5, key=lambda x: str(x.get("exit_time")), reverse=True)
        losses = sum(1 for t in window_5_desc if float(t.get("pnl_usdt") or 0.0) < 0.0)
        
        last_trade_time_str = str(window_5_desc[0].get("exit_time"))
        dt_val = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt_val = datetime.strptime(last_trade_time_str.split(".")[0].replace("T", " "), "%Y-%m-%d %H:%M:%S")
                break
            except Exception:
                pass

        if losses >= 3:
            # 24시간 이내 이벤트인지 확인
            is_24h = (dt_val and dt_val >= HOURS_24_AGO)
            trigger_events.append({
                "time": last_trade_time_str,
                "dt": dt_val,
                "losses": losses,
                "is_24h": is_24h,
                "pnl_list": [float(t.get("pnl_usdt") or 0.0) for t in window_5_desc]
            })

    # 중복 트리거 제거 (동일 5건 세트)
    unique_triggers = []
    seen_keys = set()
    for tr in trigger_events:
        t_str = tr["time"]
        if t_str not in seen_keys:
            seen_keys.add(t_str)
            unique_triggers.append(tr)

    # 5. 실제 로그에서 [AUTO MODE SWITCH] 발생 기록 검색
    log_switches = []
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "[AUTO MODE SWITCH]" in line:
                    log_switches.append(line.strip())

    report[bot] = {
        "code_ok": code_ok,
        "total_closed": len(closed_trades),
        "recent_24h_closed_count": len(recent_24h_closed),
        "triggers_all": len(unique_triggers),
        "triggers_24h": [t for t in unique_triggers if t["is_24h"]],
        "log_switches_count": len(log_switches),
        "log_switches_sample": log_switches[-3:] if log_switches else []
    }

print("=== 봇별 정밀 검증 결과 요약 ===")
for bot, r in report.items():
    print(f"\n[🤖 봇 {bot}]")
    print(f"  - 알고리즘 코드 검증: {'✅ PASS (최근 5건 중 3패 조건 수식 정확)' if r['code_ok'] else '❌ FAIL'}")
    print(f"  - 총 누적 청산 거래: {r['total_closed']}건")
    print(f"  - 최근 24시간 청산 거래: {r['recent_24h_closed_count']}건")
    print(f"  - 최근 24시간 스위칭 조건(5전 3패) 발생 횟수: {len(r['triggers_24h'])}회")
    if r['triggers_24h']:
        for idx, tr in enumerate(r['triggers_24h'], 1):
            print(f"    └ Trigger #{idx}: 발생시각={tr['time']}, 손실건수={tr['losses']}/5 (PnL: {tr['pnl_list']})")
    print(f"  - 실시간 로그상 [AUTO MODE SWITCH] 스위칭 실행 횟수: {r['log_switches_count']}회")
    if r['log_switches_sample']:
        print(f"    └ 최근 실행 로그 예시: {r['log_switches_sample'][-1]}")

