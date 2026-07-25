import os

ROOT = '/Users/l/project'
bots = ['8401', '8402', '8403', '8404', '8405', '8407', '8408', '8409']

template = """import pytest, os
from datetime import datetime, timezone, timedelta
from core.config import CFG
from core.engine import QuantumEngine
from core.logger import log_trade, _ensure_file

def test_auto_mode_switch_logic():
    csv_p = "/Users/l/project/{BOT_ID}/data/trade_history.csv"
    if os.path.exists(csv_p):
        with open(csv_p, "w", encoding="utf-8") as f:
            f.write("timestamp,symbol,type,side,price,amount,pnl_usdt,pnl_pct,exit_type,order_id,trade_id,trade_mode\\n")
            
    CFG.USE_AUTO_MODE_SWITCH = True
    CFG.USE_BLUEFROG = True  # 초기값: 청개구리 모드 (역방향)

    engine = QuantumEngine.get_instance()
    engine.cfg = CFG
    engine._last_switched_trade_keys = None

    # 5건 중 3건 손실(pnl < 0) 모의 데이터 기록
    now = datetime.now(timezone(timedelta(hours=9)))
    
    trades = [
        {"timestamp": now, "symbol": "TEST_SW/USDT", "type": "진입", "side": "buy", "price": 100, "amount": 1, "pnl_usdt": 0, "pnl_pct": 0, "order_id": "SW_1", "trade_id": "SW_1_T", "trade_mode": "역방향"},
        {"timestamp": now + timedelta(minutes=1), "symbol": "TEST_SW/USDT", "type": "청산", "side": "sell", "price": 95, "amount": 1, "pnl_usdt": -5.0, "pnl_pct": -5.0, "exit_type": "SL", "order_id": "SW_2", "trade_id": "SW_2_T", "trade_mode": "역방향"},
        
        {"timestamp": now + timedelta(minutes=2), "symbol": "TEST_SW/USDT", "type": "진입", "side": "buy", "price": 100, "amount": 1, "pnl_usdt": 0, "pnl_pct": 0, "order_id": "SW_3", "trade_id": "SW_3_T", "trade_mode": "역방향"},
        {"timestamp": now + timedelta(minutes=3), "symbol": "TEST_SW/USDT", "type": "청산", "side": "sell", "price": 95, "amount": 1, "pnl_usdt": -5.0, "pnl_pct": -5.0, "exit_type": "SL", "order_id": "SW_4", "trade_id": "SW_4_T", "trade_mode": "역방향"},

        {"timestamp": now + timedelta(minutes=4), "symbol": "TEST_SW/USDT", "type": "진입", "side": "buy", "price": 100, "amount": 1, "pnl_usdt": 0, "pnl_pct": 0, "order_id": "SW_5", "trade_id": "SW_5_T", "trade_mode": "역방향"},
        {"timestamp": now + timedelta(minutes=5), "symbol": "TEST_SW/USDT", "type": "청산", "side": "sell", "price": 95, "amount": 1, "pnl_usdt": -5.0, "pnl_pct": -5.0, "exit_type": "SL", "order_id": "SW_6", "trade_id": "SW_6_T", "trade_mode": "역방향"},

        {"timestamp": now + timedelta(minutes=6), "symbol": "TEST_SW/USDT", "type": "진입", "side": "buy", "price": 100, "amount": 1, "pnl_usdt": 0, "pnl_pct": 0, "order_id": "SW_7", "trade_id": "SW_7_T", "trade_mode": "역방향"},
        {"timestamp": now + timedelta(minutes=7), "symbol": "TEST_SW/USDT", "type": "청산", "side": "sell", "price": 105, "amount": 1, "pnl_usdt": 5.0, "pnl_pct": 5.0, "exit_type": "TP", "order_id": "SW_8", "trade_id": "SW_8_T", "trade_mode": "역방향"},

        {"timestamp": now + timedelta(minutes=8), "symbol": "TEST_SW/USDT", "type": "진입", "side": "buy", "price": 100, "amount": 1, "pnl_usdt": 0, "pnl_pct": 0, "order_id": "SW_9", "trade_id": "SW_9_T", "trade_mode": "역방향"},
        {"timestamp": now + timedelta(minutes=9), "symbol": "TEST_SW/USDT", "type": "청산", "side": "sell", "price": 105, "amount": 1, "pnl_usdt": 5.0, "pnl_pct": 5.0, "exit_type": "TP", "order_id": "SW_10", "trade_id": "SW_10_T", "trade_mode": "역방향"},
    ]

    for t in trades:
        log_trade(t)

    # 초기 모드: True (역방향)
    assert CFG.USE_BLUEFROG is True

    # 5전 3패 감지 ➡️ 모드 반전 체크 실행
    engine.check_auto_mode_switch()

    # 결과: 최근 5건 중 3건 손실(-5, -5, -5, +5, +5) 감지되어 USE_BLUEFROG 가 False(순방향)로 스위칭되어야 함!
    assert CFG.USE_BLUEFROG is False
"""

for b in bots:
    p = os.path.join(ROOT, b, 'tests', f'test_auto_mode_switch_{b}.py')
    code = template.replace('{BOT_ID}', b)
    with open(p, "w", encoding="utf-8") as f:
        f.write(code)
    print(f"✅ [{b}] 유닛 테스트 코드 표준화 작성 완료")
