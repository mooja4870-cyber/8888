import os

bb_mr_code = """\"\"\"
AI QUANTUM — 전략 8405: BB MR (Bollinger Band Mean Reversion / 15m Timeframe)
\"\"\"
import pandas as pd
import numpy as np
from dataclasses import dataclass
from core.config import CFG
import logging

logger = logging.getLogger(__name__)

@dataclass
class Signal:
    @property
    def price(self) -> float:
        return getattr(self, "close", 0.0)

    symbol: str
    direction: str          # "long" | "short" | "none"
    strength: int           # 0~100
    ema_ok: bool            # UI 호환용 더미 필드
    bb_ok: bool             # UI 호환용 더미 필드
    macd_ok: bool           # UI 호환용 더미 필드
    close: float
    rsi: float = 0.0
    reason: str = ""
    strategy_type: str = "Mean Reversion"

    sl_price: float = 0.0
    tp_price: float = 0.0

    regime: str = "Mean Reversion"
    atr: float = 0.0
    adx: float = 0.0
    bb_mid: float = 0.0
    swing_sl_price: float = 0.0
    tp1_price: float = 0.0

class StrategyEngine:
    def __init__(self, cfg=CFG):
        self.cfg = cfg
        self.period = getattr(self.cfg, "BB_PERIOD", 20)
        self.std_dev = getattr(self.cfg, "BB_STD_DEV", 2.0)
        self.sl_mult = 2.5 # 15m 최적화 파라미터
        self.rsi_thresh = 30 # 15m 최적화 파라미터
        self.market_data = {} 

    async def update_trend(self, symbol: str):
        pass

    def generate_signal(self, df: pd.DataFrame, symbol: str, **kwargs) -> Signal:
        try:
            if df is None or df.empty or len(df) < max(self.period, 14) + 1:
                return self._none_signal(symbol, 0)

            close = df["close"]
            high = df["high"]
            low = df["low"]

            # Bollinger Bands
            sma = close.rolling(window=self.period).mean()
            std = close.rolling(window=self.period).std()
            upper = sma + (std * self.std_dev)
            lower = sma - (std * self.std_dev)

            # ATR
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(window=14).mean()
            
            # RSI (Wilder)
            delta = close.diff()
            gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
            loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
            rs = gain / loss
            rsi_series = 100 - (100 / (1 + rs))

            # 완성봉 기준(-2)
            c = close.iloc[-2]
            up = upper.iloc[-2]
            dn = lower.iloc[-2]
            sma_val = sma.iloc[-2]
            a = atr.iloc[-2]
            rsi = rsi_series.iloc[-2]

            if pd.isna(c) or pd.isna(up) or pd.isna(dn) or pd.isna(a) or pd.isna(rsi):
                return self._none_signal(symbol, c)

            direction = "none"
            sl_price = 0.0
            tp_price = 0.0
            
            # BB 평균회귀 + RSI 극단 (백테스트 15m 최적화)
            if c < dn and rsi < self.rsi_thresh:
                direction = "long"
                sl_price = c - (a * self.sl_mult)
                tp_price = sma_val
                if tp_price <= c: tp_price = c + (a * 1.0)
            elif c > up and rsi > (100 - self.rsi_thresh):
                direction = "short"
                sl_price = c + (a * self.sl_mult)
                tp_price = sma_val
                if tp_price >= c: tp_price = c - (a * 1.0)

            if direction != "none":
                logger.info(f"[BB_MR SIGNAL] {symbol} {direction.upper()} | Close: {c:.4f} | BB({up:.4f}, {dn:.4f}) | RSI: {rsi:.1f} | SL: {sl_price:.4f} | TP: {tp_price:.4f}")

            return Signal(
                symbol=symbol,
                direction=direction,
                strength=80 if direction != "none" else 0,
                ema_ok=True,
                bb_ok=True,
                macd_ok=True,
                close=c,
                sl_price=sl_price,
                tp_price=tp_price,
                atr=float(a),
                bb_mid=float((up + dn) / 2.0),
                swing_sl_price=sl_price,
                tp1_price=tp_price,
            )
        except Exception as e:
            logger.error(f"[STRATEGY] BB_MR 계산 에러 ({symbol}): {e}")
            return self._none_signal(symbol, 0)

    def _none_signal(self, symbol: str, close: float) -> Signal:
        return Signal(symbol, "none", 0, False, False, False, close)
"""

filepath = "/Users/l/project/8405/core/strategy.py"
with open(filepath, "w") as f:
    f.write(bb_mr_code)
print("8405 Strategy updated.")
