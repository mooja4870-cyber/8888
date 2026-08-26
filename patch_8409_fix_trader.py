#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8409 봇 (Binance 선물) QAR-ARE (Quantum Adaptive Regime & Dynamic Volatility-Targeted Engine) 패치 스크립트
"""
import os
import sys
import json
import subprocess

BOT_DIR = "/Users/l/project/8409"


def patch_trader_py():
    trader_path = os.path.join(BOT_DIR, "core", "trader.py")
    with open(trader_path, "r", encoding="utf-8") as f:
        code = f.read()

    # 잘못 들어간 672행 블록 교체
    faulty = '''            elif sig.strategy_type == "QAR-ARE":
            # [2026-08-26] QAR-ARE 신호 강도 게이트 (60% 이상 통과)
            required_strength = 60
        elif sig.strategy_type == "DualBB":'''

    correct = '''            elif sig.strategy_type == "QAR-ARE":
                # [2026-08-26] QAR-ARE Triple Barrier (2.5 ATR TP / 1.2 ATR SL)
                sl_abs = float(getattr(sig, "swing_sl_price", 0.0) or 0.0)
                tp_abs = float(getattr(sig, "tp1_price", 0.0) or 0.0)
                if sl_abs > 0 and sig.close > 0:
                    dynamic_sl_pct = abs(sig.close - sl_abs) / sig.close
                else:
                    dynamic_sl_pct = getattr(self.cfg, "STOP_LOSS_PCT", 0.012)
                if tp_abs > 0 and sig.close > 0:
                    dynamic_tp_pct = abs(tp_abs - sig.close) / sig.close
                else:
                    dynamic_tp_pct = dynamic_sl_pct * 2.08
                logger.info(
                    f"[QAR-ARE Triple Barrier] {sig.symbol} SL={dynamic_sl_pct*100:.3f}% "
                    f"TP={dynamic_tp_pct*100:.3f}% (RR {dynamic_tp_pct/dynamic_sl_pct:.2f}:1)"
                )
            elif sig.strategy_type == "DualBB":'''

    if faulty in code:
        code = code.replace(faulty, correct)
    elif 'elif sig.strategy_type == "QAR-ARE":' not in code:
        target = '            elif sig.strategy_type == "DualBB":'
        code = code.replace(target, correct)

    with open(trader_path, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ core/trader.py QAR-ARE SL/TP 및 강도 게이트 수정 완료")


if __name__ == "__main__":
    patch_trader_py()
