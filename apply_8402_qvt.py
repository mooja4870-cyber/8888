#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_8402_qvt.py — 8402 QVT 눌림목 스나이퍼 전략 및 설정 적용 스크립트
"""
import os
import json
import shutil
from datetime import datetime

BOT_DIR = "/Users/l/project/8402"

def main():
    print("=== [8402] QVT 눌림목 스나이퍼 전략 적용 시작 ===")
    
    # 1. 과거 36.9일 데이터 아카이브
    hist_src = os.path.join(BOT_DIR, "data/trade_history.csv")
    hist_dst = os.path.join(BOT_DIR, "data/legacy_history_36d.csv")
    if os.path.exists(hist_src) and not os.path.exists(hist_dst):
        shutil.copy2(hist_src, hist_dst)
        print(f"[OK] 과거 장부 백업 완료: {hist_dst}")

    # 2. stats.json 기준선 클린 리셋 (현재 시점 기준)
    stats_path = os.path.join(BOT_DIR, "data/stats.json")
    if os.path.exists(stats_path):
        with open(stats_path, "r", encoding="utf-8") as f:
            stats = json.load(f)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats["perf_start_time"] = now_str
        stats["total_trades"] = 0
        stats["total_wins"] = 0
        stats["total_losses"] = 0
        stats["total_pnl_usdt"] = 0.0
        stats["orders_today"] = 0
        stats["daily_pnl_usdt"] = 0.0
        stats["seed_money"] = 9.74
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        print(f"[OK] stats.json 벤치마크 기준선 갱신 완료 (시작일시: {now_str}, 기준시드: $9.74)")

    # 3. config.json 설정 업데이트
    cfg_path = os.path.join(BOT_DIR, "config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg["STRATEGY_NAME"] = "QVT_Pullback_Sniper"
    cfg["USE_REGIME_ROUTER"] = False
    cfg["MAX_POSITIONS"] = 2
    cfg["MARGIN_USDT"] = 3.5
    cfg["DYNAMIC_SL_CAP_PCT"] = 0.015
    cfg["MAX_SL_PCT"] = 0.015
    cfg["TARGET_TP_PCT"] = 0.045
    cfg["USE_BE_GUARD"] = True
    cfg["BE_GUARD_TRIGGER_PCT"] = 0.020
    cfg["BE_GUARD_PROTECT_PCT"] = 0.002
    cfg["USE_TRAILING_STOP"] = True
    cfg["TRAILING_ACTIVATE_PCT"] = 0.025
    cfg["TRAILING_CALLBACK_PCT"] = 0.008
    cfg["DASHBOARD_META"] = {
        "strategy": "QVT 눌림목 스나이퍼 (1h)",
        "indicators": "Kaufman KER, 4h EMA50/200, RSI Pullback, 1:3 RR",
        "auto_switch": False
    }

    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
    print(f"[OK] config.json 파라미터 업데이트 완료 (SL 1.5%, TP 4.5%, BE 2.0%, 슬롯 2개)")

    # 4. core/strategy.py 작성
    strategy_code = '''"""
AI QUANTUM 8402 — QVT 눌림목 스나이퍼 전략 (QVT Pullback Sniper)
─────────────────────────────────────────────────────────────────────────────
월 4~7% 복리 안정 우상향을 위한 학술 및 퀀트 금융공학 기반 스나이퍼 엔진

핵심 원리
1. [Macro Trend Gate]
   - 상위 추세(EMA 50 / EMA 200 정배열 및 종가 위치)를 기준으로만 시장 진입 허용.
   - 상승 추세에서는 오직 LONG, 하락 추세에서는 오직 SHORT만 허용 (역추세 원천 차단).

2. [Kaufman KER Filter (Efficiency Ratio)]
   - Perry Kaufman (2013) 효율성 비율: 노이즈/횡보 구간(KER < 0.20) 진입 원천 봉쇄.
   - 추세 에너지가 명확히 살아있는 종목만 선별.

3. [Pullback Reversal Sniper]
   - 고점 추격 돌파(Breakout)의 가짜 돌파(Fakeout) 한계를 극복.
   - 추세 방향 진행 중 일시적 숨고르기(RSI 33~48 눌림목, 볼린저 하단/EMA20 지지선 터치) 후
     양봉 반등 또는 아래꼬리(Pinbar Wick) 확인 시 정밀 스나이핑.

4. [Asymmetric Risk Engine (1:3.0 RR)]
   - 손절(SL): 진입가 ± 1.5% (칼손절)
   - 익절(TP): 진입가 ∓ 4.5% (손익비 정확히 1:3.0)
   - 본전 보호: +2.0% 수익 도달 시 스탑로스를 본전+수수료로 상향(Breakeven Lock)
─────────────────────────────────────────────────────────────────────────────
"""
import logging
from dataclasses import dataclass
import numpy as np
import pandas as pd
from core.config import CFG

logger = logging.getLogger(__name__)

STRATEGY_NAME = "QVT_Pullback"
REGIME_NAME = "QVT 눌림목 스나이퍼"


@dataclass
class Signal:
    """UI·스캐너·트레이더 공용 시그널 객체"""
    symbol: str
    direction: str          # "long" | "short" | "none"
    strength: int           # 0~100
    ema_ok: bool            # EMA 추세 필터 통과 여부
    bb_ok: bool             # 볼린저/지지선 터치 여부
    macd_ok: bool           # KER / 모멘텀 필터 통과 여부
    close: float
    ema200: float           # 장기 기준선
    bb_upper: float         # 상단 저항선
    bb_lower: float         # 하단 지지선
    macd_hist: float        # KER 효율성 비율(%)
    reason: str
    rsi: float = 50.0
    rsi_ok: bool = True
    ema200_ok: bool = True
    atr: float = 0.0
    adx: float = 0.0
    regime: str = REGIME_NAME
    strategy_type: str = STRATEGY_NAME
    bb_mid: float = 0.0           # 목표가 (TP)
    vol_ok: bool = True
    swing_sl_price: float = 0.0   # 손절가 (SL)
    tp1_price: float = 0.0        # 익절가 (TP)
    entry_price: float = 0.0
    trend_ok: bool = True
    ema_align_ok: bool = True
    pullback_ok: bool = True
    rsi_range_ok: bool = True
    bb_break_ok: bool = True
    bb_rsi_ok: bool = True
    trend_dir: int = 0


class StrategyEngine:
    """QVT 눌림목 스나이퍼 엔진"""

    def __init__(self, cfg=None):
        self.cfg = cfg or CFG
        self.client = None

    async def update_trend(self, symbol: str):
        """[스캐너 호환 인터페이스]"""
        return

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """핵심 퀀트 지표 계산: EMA, BB, RSI, ATR, Kaufman KER"""
        if df is None or len(df) < 55:
            return pd.DataFrame()

        d = df.copy()
        close = d['close']
        high = d['high']
        low = d['low']

        # 1. EMA 추세선 (20, 50, 200)
        d['ema20'] = close.ewm(span=20, adjust=False).mean()
        d['ema50'] = close.ewm(span=50, adjust=False).mean()
        d['ema200'] = close.ewm(span=min(200, len(d) - 1), adjust=False).mean()

        # 2. RSI (14)
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        d['rsi'] = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(50.0)

        # 3. Bollinger Bands (20, 2.0 std)
        bb_sma = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        d['bb_mid'] = bb_sma
        d['bb_upper'] = bb_sma + 2.0 * bb_std
        d['bb_lower'] = bb_sma - 2.0 * bb_std

        # 4. ATR (14)
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        d['atr'] = tr.ewm(alpha=1 / 14, adjust=False).mean()

        # 5. Kaufman Efficiency Ratio (KER - 20)
        change = (close - close.shift(20)).abs()
        volatility = close.diff().abs().rolling(20).sum()
        d['ker'] = (change / (volatility + 1e-10)).fillna(0.2)

        return d

    def _no(self, symbol: str, reason: str, curr=None) -> Signal:
        """진입 미충족 관망 신호"""
        if curr is None:
            return Signal(
                symbol=symbol, direction="none", strength=0,
                ema_ok=False, bb_ok=False, macd_ok=False,
                close=0.0, ema200=0.0, bb_upper=0.0, bb_lower=0.0,
                macd_hist=0.0, reason=reason
            )
        return Signal(
            symbol=symbol, direction="none", strength=0,
            ema_ok=False, bb_ok=False, macd_ok=False,
            close=float(curr['close']),
            ema200=float(curr['ema200']),
            bb_upper=float(curr['bb_upper']),
            bb_lower=float(curr['bb_lower']),
            macd_hist=float(curr['ker'] * 100.0),
            reason=reason,
            rsi=float(curr['rsi']),
            atr=float(curr['atr']),
            entry_price=float(curr['close']),
        )

    def generate_signal(self, df: pd.DataFrame, symbol: str, **kwargs) -> Signal:
        """QVT 눌림목 스나이퍼 신호 판정"""
        allow_l = bool(getattr(self.cfg, 'ALLOW_LONG', True))
        allow_s = bool(getattr(self.cfg, 'ALLOW_SHORT', True))
        sl_pct = float(getattr(self.cfg, 'MAX_SL_PCT', 0.015))
        tp_pct = float(getattr(self.cfg, 'TARGET_TP_PCT', 0.045))

        d = self.calculate_indicators(df)
        if d.empty:
            return self._no(symbol, "데이터 부족 (관망)")

        d = d.iloc[:-1]  # 미완성 현재봉 배제 (미래참조 방지)
        if len(d) < 30:
            return self._no(symbol, "캔들 수 부족 (관망)")

        curr = d.iloc[-1]
        c = float(curr['close'])
        o = float(curr['open'])
        h = float(curr['high'])
        l = float(curr['low'])
        ema20 = float(curr['ema20'])
        ema50 = float(curr['ema50'])
        ema200 = float(curr['ema200'])
        rsi = float(curr['rsi'])
        bb_low = float(curr['bb_lower'])
        bb_high = float(curr['bb_upper'])
        atr = float(curr['atr'])
        ker = float(curr['ker'])

        if c <= 0 or atr <= 0:
            return self._no(symbol, "가격/지표 이상 (관망)", curr)

        # 1. Kaufman 효율성 비율 (KER): 횡보/노이즈 차단
        if ker < 0.20:
            return self._no(symbol, f"횡보장 노이즈 차단 (KER {ker:.2f} < 0.20)", curr)

        # 2. 캔들 형태학 판정 (Pinbar 아래꼬리/위꼬리)
        body = abs(c - o)
        candle_range = h - l if (h - l) > 0 else 1e-8
        lower_wick = min(c, o) - l
        upper_wick = h - max(c, o)
        has_bull_pinbar = (lower_wick >= candle_range * 0.35) or (c > o)
        has_bear_pinbar = (upper_wick >= candle_range * 0.35) or (c < o)

        # 3. LONG 스나이퍼 조건
        # - 상승 추세: EMA50 > EMA200 및 Close > EMA50 * 0.985
        # - 눌림목: RSI 33 ~ 48
        # - 지지선 터치: 저가가 BB 하단 또는 EMA20 대비 +1.0% 이내 접촉
        # - 반등 확인: 양봉 또는 아래꼬리 핀바
        long_trend_ok = (ema50 > ema200) and (c > ema50 * 0.985)
        long_pullback_rsi = (32.0 <= rsi <= 48.0)
        long_support_touch = (l <= bb_low * 1.01) or (l <= ema20 * 1.008)
        
        # 4. SHORT 스나이퍼 조건
        # - 하락 추세: EMA50 < EMA200 및 Close < EMA50 * 1.015
        # - 되돌림: RSI 52 ~ 68
        # - 저항선 터치: 고가가 BB 상단 또는 EMA20 대비 -1.0% 이내 접촉
        # - 반락 확인: 음봉 또는 위꼬리 핀바
        short_trend_ok = (ema50 < ema200) and (c < ema50 * 1.015)
        short_pullback_rsi = (52.0 <= rsi <= 68.0)
        short_resistance_touch = (h >= bb_high * 0.99) or (h >= ema20 * 0.992)

        direction = "none"
        if allow_l and long_trend_ok and long_pullback_rsi and long_support_touch and has_bull_pinbar:
            direction = "long"
            sl_price = round(c * (1.0 - sl_pct), 6)
            tp_price = round(c * (1.0 + tp_pct), 6)
            reason = (f"상승추세(EMA50>200) + RSI눌림({rsi:.1f}) + 지지반등 + KER({ker:.2f}) "
                      f"| SL-{sl_pct*100:.1f}% / TP+{tp_pct*100:.1f}% (RR 1:3.0)")
        elif allow_s and short_trend_ok and short_pullback_rsi and short_resistance_touch and has_bear_pinbar:
            direction = "short"
            sl_price = round(c * (1.0 + sl_pct), 6)
            tp_price = round(c * (1.0 - tp_pct), 6)
            reason = (f"하락추세(EMA50<200) + RSI되돌림({rsi:.1f}) + 저항반락 + KER({ker:.2f}) "
                      f"| SL+{sl_pct*100:.1f}% / TP-{tp_pct*100:.1f}% (RR 1:3.0)")
        else:
            if long_trend_ok:
                why = f"상승추세 진행중이나 눌림 대기 (RSI {rsi:.1f}, KER {ker:.2f})"
            elif short_trend_ok:
                why = f"하락추세 진행중이나 되돌림 대기 (RSI {rsi:.1f}, KER {ker:.2f})"
            else:
                why = f"중립 추세 관망 (RSI {rsi:.1f}, KER {ker:.2f})"
            return self._no(symbol, why, curr)

        logger.info(f"[QVT-SNIPER] {symbol} {direction.upper()} 포착 | 종가 {c} | "
                    f"RSI {rsi:.1f} | SL {sl_price} | TP {tp_price} | 이유: {reason}")

        return Signal(
            symbol=symbol,
            direction=direction,
            strength=100,
            ema_ok=True,
            bb_ok=True,
            macd_ok=True,
            close=c,
            ema200=ema200,
            bb_upper=bb_high,
            bb_lower=bb_low,
            macd_hist=float(ker * 100.0),
            reason=reason,
            rsi=rsi,
            rsi_ok=True,
            ema200_ok=True,
            atr=atr,
            adx=float(ker * 100.0),
            regime=REGIME_NAME,
            strategy_type=STRATEGY_NAME,
            bb_mid=tp_price,
            vol_ok=True,
            swing_sl_price=sl_price,
            tp1_price=tp_price,
            entry_price=c,
            trend_ok=True,
            ema_align_ok=True,
            pullback_ok=True,
            rsi_range_ok=True,
            bb_break_ok=True,
            bb_rsi_ok=True,
            trend_dir=1 if direction == "long" else -1,
        )
'''
    strat_path = os.path.join(BOT_DIR, "core/strategy.py")
    with open(strat_path, "w", encoding="utf-8") as f:
        f.write(strategy_code)
    print(f"[OK] core/strategy.py 작성 완료: {strat_path}")

    # 5. core/trader.py 확인 및 보완 (QVT_Pullback 신호 강도 게이트 0 처리)
    trader_path = os.path.join(BOT_DIR, "core/trader.py")
    with open(trader_path, "r", encoding="utf-8") as f:
        trader_src = f.read()

    if '"QVT_Pullback"' not in trader_src:
        trader_src = trader_src.replace(
            'elif sig.strategy_type == "MACross":',
            'elif sig.strategy_type in ("MACross", "QVT_Pullback"):'
        )
        with open(trader_path, "w", encoding="utf-8") as f:
            f.write(trader_src)
        print("[OK] core/trader.py QVT_Pullback 전략 게이트 등록 완료")
    else:
        print("[OK] core/trader.py QVT_Pullback 전략 게이트 이미 등록됨")

    print("=== [8402] 모든 파일 수정 및 설정 반영 완료 ===")

if __name__ == "__main__":
    main()
