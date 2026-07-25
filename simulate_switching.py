#!/usr/bin/env python3
"""
8개 봇의 과거 매매 이력 데이터를 기반으로
다양한 자동 스위칭(매매방향 반전) 조건 시뮬레이션 분석 스크립트 (봇별 상세 포함)
"""

import os
import pandas as pd

BOT_DIRS = {
    "8401": "/Users/l/project/8401",
    "8402": "/Users/l/project/8402",
    "8403": "/Users/l/project/8403",
    "8404": "/Users/l/project/8404",
    "8405": "/Users/l/project/8405",
    "8407": "/Users/l/project/8407",
    "8408": "/Users/l/project/8408",
    "8409": "/Users/l/project/8409",
}

SCENARIOS = [
    {"name": "1. 스위칭 없음 (순방향 고정)", "type": "fixed", "mode": "순방향"},
    {"name": "2. 스위칭 없음 (역방향 고정)", "type": "fixed", "mode": "역방향"},
    {"name": "3. 3전 2패 스위칭 (window=3, loss>=2)", "type": "window", "window": 3, "loss_req": 2, "cooldown": 0},
    {"name": "4. 4전 3패 스위칭 (window=4, loss>=3) [현재]", "type": "window", "window": 4, "loss_req": 3, "cooldown": 0},
    {"name": "5. 5전 3패 스위칭 (window=5, loss>=3)", "type": "window", "window": 5, "loss_req": 3, "cooldown": 0},
    {"name": "6. 5전 4패 스위칭 (window=5, loss>=4)", "type": "window", "window": 5, "loss_req": 4, "cooldown": 0},
    {"name": "7. 연속 3연패 스위칭 (streak=3)", "type": "streak", "streak": 3, "cooldown": 0},
    {"name": "8. 4전 3패 + 3거래 쿨다운 (window=4, loss>=3, cd=3)", "type": "window", "window": 4, "loss_req": 3, "cooldown": 3},
]

def load_bot_trades(bot_id, path):
    csv_file = os.path.join(path, "data", "trade_history.csv")
    if not os.path.exists(csv_file):
        return []
    
    try:
        df = pd.read_csv(csv_file, encoding="utf-8-sig")
        df.columns = [c.strip() for c in df.columns]
        
        exit_df = df[df["유형"].astype(str).str.contains("청산", na=False)].copy()
        if exit_df.empty:
            return []
        
        trades = []
        for _, row in exit_df.iterrows():
            pnl = float(row.get("수익(USDT)", 0.0) or 0.0)
            mode = str(row.get("매매모드", "") or "").strip()
            if not mode:
                mode = "역방향" if bot_id in ("8401", "8404", "8408") else "순방향"
            
            if mode == "역방향":
                pnl_forward = -pnl
                pnl_reverse = pnl
            else:
                pnl_forward = pnl
                pnl_reverse = -pnl
                
            trades.append({
                "time": str(row.get("시간", "")),
                "symbol": str(row.get("심볼", "")),
                "actual_mode": mode,
                "pnl_actual": pnl,
                "pnl_forward": pnl_forward,
                "pnl_reverse": pnl_reverse,
            })
        return trades
    except Exception as e:
        return []

def run_simulation(trades, sc):
    sc_type = sc["type"]
    cur_mode = "역방향"
    
    history_outcomes = []
    switches = 0
    whipsaws = 0
    tot_pnl = 0.0
    wins = 0
    total_count = len(trades)
    
    cooldown_left = 0
    last_switched_idx = -999
    
    for i, t in enumerate(trades):
        if cur_mode == "역방향":
            trade_pnl = t["pnl_reverse"]
        else:
            trade_pnl = t["pnl_forward"]
            
        tot_pnl += trade_pnl
        is_loss = trade_pnl < 0
        if not is_loss:
            wins += 1
            
        history_outcomes.append(is_loss)
        
        if sc_type == "fixed":
            cur_mode = sc["mode"]
            continue
            
        if cooldown_left > 0:
            cooldown_left -= 1
            continue
            
        should_switch = False
        
        if sc_type == "window":
            w = sc["window"]
            req = sc["loss_req"]
            if len(history_outcomes) >= w:
                recent_w = history_outcomes[-w:]
                if sum(recent_w) >= req:
                    should_switch = True
        elif sc_type == "streak":
            s = sc["streak"]
            if len(history_outcomes) >= s:
                recent_s = history_outcomes[-s:]
                if all(recent_s):
                    should_switch = True
                    
        if should_switch:
            if (i - last_switched_idx) <= 2:
                whipsaws += 1
            last_switched_idx = i
            switches += 1
            cur_mode = "순방향" if cur_mode == "역방향" else "역방향"
            cooldown_left = sc.get("cooldown", 0)
            
    win_rate = (wins / total_count * 100) if total_count > 0 else 0.0
    return {
        "pnl": tot_pnl,
        "win_rate": win_rate,
        "switches": switches,
        "whipsaws": whipsaws,
        "trades": total_count
    }

def main():
    all_bot_trades = {}
    total_trades_count = 0
    for bot_id, path in BOT_DIRS.items():
        t = load_bot_trades(bot_id, path)
        all_bot_trades[bot_id] = t
        total_trades_count += len(t)
        
    print(f"=== 8개 봇 전체 거래수 수집 완료: 총 {total_trades_count}건 청산 거래 ===")
    print()
    
    results = []
    for sc in SCENARIOS:
        sc_pnl = 0.0
        sc_switches = 0
        sc_whipsaws = 0
        bot_details = {}
        
        for bot_id, trades in all_bot_trades.items():
            res = run_simulation(trades, sc)
            sc_pnl += res["pnl"]
            sc_switches += res["switches"]
            sc_whipsaws += res["whipsaws"]
            bot_details[bot_id] = res
            
        win_rate = (sum(res["win_rate"] * len(all_bot_trades[b]) for b, res in bot_details.items()) / total_trades_count) if total_trades_count > 0 else 0.0
        
        results.append({
            "scenario": sc["name"],
            "pnl": sc_pnl,
            "win_rate": win_rate,
            "switches": sc_switches,
            "whipsaws": sc_whipsaws,
            "bot_details": bot_details
        })
        
    print(f"{'시나리오명':<48} | {'총 손익(USDT)':<12} | {'평균 승률(%)':<10} | {'스위칭 횟수':<10} | {'휩소 횟수':<8}")
    print("-" * 98)
    for r in results:
        print(f"{r['scenario']:<48} | {r['pnl']:+12.2f} | {r['win_rate']:10.1f}% | {r['switches']:10d} | {r['whipsaws']:8d}")

    print("\n\n=== 봇별 최적 시나리오 상세 ===")
    for bot_id in sorted(BOT_DIRS.keys()):
        trades = all_bot_trades[bot_id]
        if not trades:
            continue
        print(f"\n[봇 {bot_id}] (총 {len(trades)}건 청산 거래)")
        bot_sc_res = []
        for sc in SCENARIOS:
            res = run_simulation(trades, sc)
            bot_sc_res.append((sc["name"], res["pnl"], res["win_rate"], res["switches"], res["whipsaws"]))
        bot_sc_res.sort(key=lambda x: x[1], reverse=True)
        for rank, (name, pnl, wr, sw, whip) in enumerate(bot_sc_res[:3], 1):
            print(f"  {rank}위: {name:<45} | 손익: {pnl:+7.2f} USDT | 승률: {wr:5.1f}% | 스위칭: {sw:2d}회 (휩소: {whip:2d}회)")

if __name__ == "__main__":
    main()
