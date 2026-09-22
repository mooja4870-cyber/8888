"""
AI QUANTUM — 전략 9: TSMOM (시계열 모멘텀 / 추세추종)
"""
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
    ema200: float           # UI 호환용 더미 필드
    bb_upper: float         # UI 호환용 더미 필드
    bb_lower: float         # UI 호환용 더미 필드
    rsi: float              # UI 호환용 더미 필드
    reason: str = ""        # 청산 등 상세 정보 표시
    strategy_type: str = "TSMOM"
    sl_price: float = 0.0
    tp_price: float = 0.0
    atr: float = 0.0

    # [2026-08-27 무진입 수정] 트레이더가 getattr 없이 직접 참조하는 필드.
    # 없으면 신호가 나오는 순간 AttributeError로 주문이 튕긴다
    # (8410이 MARGIN_MODE 누락으로 221건 전량 실패한 것과 같은 유형).
    regime: str = "TSMOM"
    adx: float = 0.0              # 레짐 필터 미사용 → 0
    bb_mid: float = 0.0           # 볼린저 미사용 → 0
    swing_sl_price: float = 0.0   # = sl_price. 트레이더의 스윙 SL/TP 경로를 태운다
    tp1_price: float = 0.0        # = tp_price
    volatility_ratio: float = 1.0 # [4] 변동성 배수 (현재 ATR / 장기 ATR)


class StrategyEngine:
    def __init__(self, cfg=CFG):
        self.cfg = cfg
        self.market_data = {}  # {symbol: pd.DataFrame}
        logger.info(f"TSMOM 전략 엔진 초기화 (Lookback: {getattr(self.cfg, 'TSMOM_LOOKBACK_BARS', 30)}봉, SL: {getattr(self.cfg, 'TSMOM_SL_ATR_MULT', 2.0)}ATR)")

    async def update_trend(self, symbol: str):
        """백그라운드 스캐너 등과의 인터페이스 유지를 위한 빈 메서드"""
        pass

    def load_market_data(self, symbol: str, df: pd.DataFrame):
        self.market_data[symbol] = df

    def generate_signal(self, df, symbol: str, **kwargs) -> Signal:
        # [2026-08-27 무진입 수정] 종전에는 인자로 받은 df를 첫 줄에서 버리고
        # self.market_data[symbol]을 읽었다. 그런데 그 캐시를 채우는
        # load_market_data()를 **호출하는 코드가 저장소 어디에도 없다**
        # (grep 결과 0건). 스캐너는 300봉을 받아 generate_signal(df, sym)으로
        # 넘기는데 그 df가 즉시 버려지니 모든 심볼이 매번 "데이터 부족"으로
        # 반려됐고, 신호가 단 한 건도 나오지 않았다.
        # 실측: 02:05~08:37 스캔 366회 · 신호 0건.
        # 인자를 우선 쓰되, 비어 있을 때만 캐시로 폴백한다.
        if df is None or (hasattr(df, "empty") and df.empty):
            df = self.market_data.get(symbol)
        if df is None or df.empty or len(df) < 50:
            return self._empty_signal(symbol)

        try:
            lookback = int(getattr(self.cfg, 'TSMOM_LOOKBACK_BARS', 30))
            if len(df) < lookback + 5:
                return self._empty_signal(symbol)

            # ATR 계산
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values
            
            # TR (True Range)
            tr1 = high[1:] - low[1:]
            tr2 = np.abs(high[1:] - close[:-1])
            tr3 = np.abs(low[1:] - close[:-1])
            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            
            # ATR (14) - SMA 방식
            atr = pd.Series(tr).rolling(14).mean().iloc[-1]
            if np.isnan(atr) or atr == 0:
                return self._empty_signal(symbol)

            # [4] 변동성 배수 계산
            atr_long = pd.Series(tr).rolling(100).mean().iloc[-1]
            volatility_ratio = 1.0
            if not np.isnan(atr_long) and atr_long > 0:
                volatility_ratio = atr / atr_long

            current_close = close[-1]
            
            # [5] 세션 필터 (아시아 장 돌파 기준 강화)
            session_lookback = lookback
            if getattr(self.cfg, 'ENABLE_SESSION_FILTER', False):
                import datetime
                current_utc_hour = datetime.datetime.utcnow().hour
                if 0 <= current_utc_hour < 8: # 아시아 세션 (UTC 00:00 ~ 08:00)
                    session_lookback = lookback * 2 # 기준을 2배로 깐깐하게

            # 채널은 직전 lookback봉(현재 봉 제외)의 고저를 쓴다.
            hh = float(np.max(high[-(session_lookback + 1):-1]))
            ll = float(np.min(low[-(session_lookback + 1):-1]))

            direction = "none"
            reason = f"대기 (채널 {ll:.4f}~{hh:.4f})"
            strength = 0

            sl_atr_mult = getattr(self.cfg, 'TSMOM_SL_ATR_MULT', 2.0)
            sl_price = 0.0
            tp_price = 0.0

            # 돈치안 채널 돌파 진입
            if current_close > hh:
                direction = "long"
                reason = f"상단 돌파 ({current_close:.4f} > {hh:.4f})"
                strength = min(int(((current_close / hh) - 1) * 2000) + 60, 100)
                sl_price = current_close - (atr * sl_atr_mult)
                tp_price = current_close + (atr * sl_atr_mult * 2.0)   # 손익비 1:2
            elif current_close < ll:
                direction = "short"
                reason = f"하단 돌파 ({current_close:.4f} < {ll:.4f})"
                strength = min(int((1 - (current_close / ll)) * 2000) + 60, 100)
                sl_price = current_close + (atr * sl_atr_mult)
                tp_price = current_close - (atr * sl_atr_mult * 2.0)   # 손익비 1:2

            return Signal(
                symbol=symbol,
                direction=direction,
                strength=strength,
                ema_ok=(direction != "none"),
                bb_ok=(direction != "none"),
                macd_ok=(direction != "none"),
                close=current_close,
                ema200=hh,              # UI에 채널 상단 표시 용도
                bb_upper=current_close + atr, 
                bb_lower=current_close - atr,
                rsi=atr,                # UI 표시 용도로 ATR을 rsi 자리에 꼼수로 넣기
                reason=reason,
                strategy_type="TSMOM",
                sl_price=sl_price,
                tp_price=tp_price,
                atr=atr,
                volatility_ratio=volatility_ratio,
                # 트레이더가 직접 참조하는 필드 — 비우면 주문 단계에서 터진다
                swing_sl_price=sl_price,
                tp1_price=tp_price,
            )

        except Exception as e:
            logger.error(f"[Strategy Error] {symbol}: {e}")
            return self._empty_signal(symbol)

    def _empty_signal(self, symbol: str) -> Signal:
        return Signal(
            symbol=symbol, direction="none", strength=0,
            ema_ok=False, bb_ok=False, macd_ok=False,
            close=0.0, ema200=0.0, bb_upper=0.0, bb_lower=0.0, rsi=0.0, reason="데이터 부족",
            strategy_type="TSMOM", sl_price=0.0, tp_price=0.0, atr=0.0, volatility_ratio=1.0
        )
