import subprocess, sys, json

print("==========================================================================")
print("5대 핵심 봇 (8401, 8402, 8407, 8409, 8410) 실시간 전수 감사 보고서")
print("==========================================================================")

total_balance = 0.0
total_pnl_usdt = 0.0

for b in ['8401', '8402', '8407', '8409', '8410']:
    r = subprocess.run([sys.executable, 'scratch/query_single_bot.py', b], capture_output=True, text=True)
    parsed = False
    for line in r.stdout.strip().split('\n'):
        if line.startswith('{') and line.endswith('}'):
            try:
                d = json.loads(line)
                parsed = True
                bal = d['wallet_balance']
                free = d['free_balance']
                total_balance += bal
                
                print(f"■ [{d['bot']}] {d['exchange']} 선물 봇 ({d['strategy']}, {d['timeframe']})")
                print(f"  • 총 지갑 잔고: ${bal:.4f} USDT (주문가능: ${free:.4f} USDT)")
                
                pos_list = d.get('positions', [])
                if pos_list:
                    print(f"  • 실보유 활성 포지션 ({len(pos_list)}건):")
                    for p in pos_list:
                        sym = p.get('symbol')
                        side = p.get('side')
                        entry = p.get('entry_price')
                        mark = p.get('mark_price')
                        upnl = p.get('pnl_usdt', 0.0)
                        pct = p.get('pnl_pct', 0.0)
                        cnt = p.get('size', 0)
                        init_m = p.get('margin', 0.0)
                        lev = p.get('leverage')
                        total_pnl_usdt += upnl
                        print(f"    - {sym} [{side}] | 진입가: {entry} | 현재가: {mark} | 수량: {cnt} | 미실현손익: {upnl:+.4f} USDT ({pct:+.2f}%) | 증거금: ${init_m:.2f} ({lev}x)")
                else:
                    print("  • 실보유 활성 포지션: 없음 (무포지션 대기)")
                
                rows = d.get('trade_history_rows', 0)
                print(f"  • 실거래 장부 기록: 총 {rows}건 체결 완료")
                print()
            except Exception as e:
                print(f"[{b}] Parse error: {e}")
    if not parsed:
        print(f"[{b}] Query Failed:")
        print("STDOUT:", r.stdout.strip())
        print("STDERR:", r.stderr.strip())
        print()

print(f"==========================================================================")
print(f"★ 5대 핵심 봇 총 합산 자산: ${total_balance:.4f} USDT (원금 $50.00 대비 {total_balance-50:+.4f} USDT / {(total_balance-50)/50*100:+.2f}%)")
print(f"★ 활성 포지션 총 미실현손익: {total_pnl_usdt:+.4f} USDT")
print(f"==========================================================================")
