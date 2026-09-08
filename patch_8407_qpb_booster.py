#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_8407_qpb_booster.py — 8407 봇 퀀트 수익성부스터(QPB-Alpha) 엔진 배포 및 검증 스크립트

융합된 5대 금융공학 문헌 및 헤지펀드 핵심 이론:
1. Marcos López de Prado (2018): Meta-Labeling Quality Gate & Triple Barrier Method
2. Perry Kaufman (2013): Kaufman Efficiency Ratio (KER > 0.30) 횡보장 휩쏘 원천 차단
3. Marc Chaikin & Fischer & Krauss (2018): Chaikin Money Flow(CMF) & Volume Surge(1.2x+) 동반 돌파 선별
4. AQR Capital (Asness et al., 2013): Binance 선물 마이크로구조 실시간 펀딩비 숏 스퀴즈 알파
5. Dynamic Bet Sizing & RR Scaling: Super Booster(1.4x 마진, 3.5 ATR 광폭 익절) / Normal Booster(1.0x, 2.2 ATR)
"""

import os
import sys
import json
import logging

BOT_DIR = "/Users/l/project/8407"

def verify_8407_booster():
    sys.path.insert(0, BOT_DIR)
    from core.strategy import StrategyEngine
    from core.config import CFG
    from core.profitability_booster import evaluate_profitability_booster
    import pandas as pd
    import numpy as np

    eng = StrategyEngine(CFG)
    dates = pd.date_range('2026-09-08 00:00:00', periods=80, freq='15min')
    close = 100.0 + np.linspace(0, 15, 80)
    high = close + 0.2
    low = close - 0.2
    open_p = close - 0.1
    vol = np.random.rand(80) * 500 + 200
    close[-1] = 117.0
    high[-1] = 117.5
    vol[-1] = 2500
    df = pd.DataFrame({'open': open_p, 'high': high, 'low': low, 'close': close, 'volume': vol}, index=dates)

    sig = eng.generate_signal(df, 'SOL/USDT:USDT', funding_rate=-0.0002)
    assert sig.direction == "long", f"Expected long, got {sig.direction}"
    assert "부스터" in sig.booster_tag, f"Expected booster_tag, got {sig.booster_tag}"
    assert sig.booster_sizing_mult >= 1.0, f"Expected sizing >= 1.0, got {sig.booster_sizing_mult}"
    print(f"✅ 8407 QPB-Alpha 전략 검증 성공: {sig.direction.upper()} | {sig.booster_tag} | SL={sig.sl_price:.4f} TP={sig.tp_price:.4f}")
    return True

if __name__ == "__main__":
    if verify_8407_booster():
        print("🎉 8407 퀀트 수익성부스터(QPB-Alpha) 전면 가동 검증 완료!")
