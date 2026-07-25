#!/usr/bin/env python3
"""
전체 과거 이력에 대한 5전 3패 스위칭 조건 발생 시점 대조 정밀 검증 스크립트
"""
import os
import sys
import glob
import json
from datetime import datetime

BASE_DIR = "/Users/l/project"
BOTS = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]

print(f"=== [전체 청산 이력 대상 5전 3패 스위칭 로직 100% 정밀 백테스트 & 실적 대조] ===\n")

for bot in BOTS:
    bot_dir = os.path.join(BASE_DIR, bot)
    log_file = os.path.join(bot_dir, "bot_engine.log")
    
    try:
        sys.path.insert(0, bot_dir)
        import importlib
        hh_spec = importlib.util.spec_from_file_location(f"hh_{bot}", os.path.join(bot_dir, "core", "history_helper.py"))
        hh = importlib.util.module_from_spec(hh_spec)
        hh_spec.loader.exec_module(hh)
        
        raw_trades = hh.load_local_trade_history()
        paired = hh.aggregate_and_pair_trades(raw_trades)
        closed_trades = [x for x in paired if x.get("status") == "청산 완료" and x.get("exit_time") is not None]
        # 시간순 정렬 (과거 -> 최신)
        closed_trades.sort(key=lambda x: str(x.get("exit_time")))
    except Exception as e:
        closed_trades = []

    # 전체 기간 롤링 시뮬레이션
    trigger_events = []
    last_switched_keys = None

    for i in range(len(closed_trades)):
        if i < 4:
            continue
        window_5 = closed_trades[max(0, i-4):i+1] # 5건
        window_5_desc = sorted(window_5, key=lambda x: str(x.get("exit_time")), reverse=True)
        losses = sum(1 for t in window_5_desc if float(t.get("pnl_usdt") or 0.0) < 0.0)
        
        if losses >= 3:
            current_5_keys = tuple(sorted([str(t.get("exit_time")) for t in window_5_desc]))
            if current_5_keys != last_switched_keys:
                last_switched_keys = current_5_keys
                trigger_events.append({
                    "trade_index": i + 1,
                    "exit_time": str(window_5_desc[0].get("exit_time")),
                    "losses": losses,
                    "symbol": window_5_desc[0].get("symbol"),
                    "pnl_sequence": [float(t.get("pnl_usdt") or 0.0) for t in window_5_desc]
                })

    # 로그 검색
    log_switches = []
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "적응형" in line or "AUTO MODE SWITCH" in line or "대칭 반전" in line:
                    log_switches.append(line.strip())

    print(f"🤖 [봇 {bot}]")
    print(f"  - 총 청산 완료 거래 수: {len(closed_trades)}건")
    print(f"  - 이론적 5전 3패 스위칭 조건 발동 횟수: {len(trigger_events)}회")
    if trigger_events:
        print(f"  - 스위칭 조건 발동 시점 이력:")
        for idx, ev in enumerate(trigger_events, 1):
            print(f"    └ #{idx}: [{ev['exit_time']}] 종목={ev['symbol']} | 5건 중 손실={ev['losses']}건 | PnL={ev['pnl_sequence']}")
    else:
        print(f"  - 5전 3패 조건 달성 이력 없음 (손실 연속 감지되지 않음)")
    
    print(f"  - 실제 로그 기록된 스위칭 수: {len(log_switches)}건")
    if log_switches:
        print(f"    └ 최근 스위칭 로그: {log_switches[-1]}")
    print("-" * 65)

