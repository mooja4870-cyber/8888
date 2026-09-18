import ccxt, json, os

bots = {
    '8401': {'ex': 'okx', 'symbols': ['DOT/USDT:USDT']},
    '8402': {'ex': 'okx', 'symbols': ['DOT/USDT:USDT']},
    '8407': {'ex': 'binance', 'symbols': ['ENA/USDT:USDT', 'USELESS/USDT:USDT', 'LIT/USDT:USDT']},
    '8409': {'ex': 'binance', 'symbols': ['ASTER/USDT:USDT']},
    '8410': {'ex': 'binance', 'symbols': ['BNB/USDT:USDT', 'AR/USDT:USDT', 'DOT/USDT:USDT']}
}

for b, info in bots.items():
    cfg_p = f'/Users/l/project/{b}/config.json'
    with open(cfg_p, 'r') as f:
        cfg = json.load(f)
    ex_id = info['ex']
    if ex_id == 'okx':
        exchange = ccxt.okx({
            'apiKey': cfg.get('EXCHANGE_API_KEY'),
            'secret': cfg.get('EXCHANGE_SECRET_KEY'),
            'password': cfg.get('EXCHANGE_PASSPHRASE'),
            'options': {'defaultType': 'swap'}
        })
    else:
        exchange = ccxt.binance({
            'apiKey': cfg.get('EXCHANGE_API_KEY'),
            'secret': cfg.get('EXCHANGE_SECRET_KEY'),
            'options': {'defaultType': 'future'}
        })
    try:
        raw_pos = exchange.fetch_positions(info['symbols'])
        print(f"=== BOT {b} ({ex_id.upper()}) ===")
        found = False
        for p in raw_pos:
            contracts = float(p.get('contracts') or 0)
            if contracts > 0:
                found = True
                sym = p.get('symbol')
                side = p.get('side', '').upper()
                entry = p.get('entryPrice')
                mark = p.get('markPrice')
                upnl = float(p.get('unrealizedPnl') or 0)
                pct = float(p.get('percentage') or 0)
                lev = p.get('leverage')
                init_margin = float(p.get('initialMargin') or 0)
                print(f"  • {sym} | 방향: {side} | 진입가: {entry} | 현재가: {mark} | 수량: {contracts} | 미실현손익: {upnl:+.4f} USDT ({pct:+.2f}%) | 마진: ${init_margin:.2f} ({lev}x)")
        if not found:
            print("  • (활성 체결 포지션 없음 / 0 계약)")
            
        bal = exchange.fetch_balance()
        usdt_total = bal.get('USDT', {}).get('total', 0)
        usdt_free = bal.get('USDT', {}).get('free', 0)
        print(f"  [지갑 잔고] Total USDT: ${usdt_total:.4f} (가용: ${usdt_free:.4f})")
    except Exception as e:
        print(f"Error fetching {b}: {e}")
    print()

