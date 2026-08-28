"""
🚀 8407 딥러닝 전략 혁신 (Enhanced Deep Learning Strategy v2.0)
════════════════════════════════════════════════════════════════════════

[문제 분석]
- 기존 Stub 모델: 3개 피처만 사용 (ret_1, ret_5, vol)
- 신호 품질 낮음: threshold 55% (거의 랜덤)
- 단방향만 가능: 역방향/헤징 전략 없음
- 적응성 부족: 시장 정권 변화 대응 불가

[혁신 전략]
1. 다층 신호 시스템 (5가지 신호 결합)
2. 부가 매매 전략 (Contrarian, Hedging, Multi-regime)
3. 동적 위치 관리 (변동성 기반 사이징)
4. 확률 및 신호 강화 (ensemble voting)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from core.config import CFG
import logging
import math
from typing import Tuple, List

logger = logging.getLogger(__name__)

@dataclass
class Signal:
    symbol: str
    direction: str          # "long" | "short" | "none"
    price: float
    sl_price: float
    tp_price: float
    regime: str
    prob: float
    strength: float = 0.0
    rsi: float = 50.0
    reason: str = ''
    strategy_type: str = "DeepLearningEnhanced"

    # Trader compatibility fields
    close: float = 0.0
    atr: float = 0.0
    adx: float = 0.0
    bb_mid: float = 0.0
    swing_sl_price: float = 0.0
    tp1_price: float = 0.0

    # 🆕 Enhanced fields
    signal_sources: List[str] = None  # 신호 출처 (어떤 지표 조합인지)
    confidence: float = 0.0             # 신뢰도 (0~1)
    multi_timeframe: bool = False       # 다중시간대 확인 여부


class EnhancedStrategyEngine:
    """
    8407 전략 고도화 엔진

    5가지 신호 결합:
    1. DL Momentum (딥러닝 모멘텀)
    2. Mean Reversion (평균회귀)
    3. Trend Following (추세추종)
    4. Volatility Adaptive (변동성 적응)
    5. Volume Confirmation (거래량 확인)
    """

    def __init__(self, cfg=None):
        self.cfg = cfg or CFG
        self.model_loaded = True  # Stub이지만 항상 로드됨으로 간주

        # 신호 캐시 (이전 신호 기억)
        self.prev_signal_direction = {}
        self.signal_count = 0
        self.win_count = 0

        # 설정값
        self.base_prob_threshold = getattr(cfg, 'DL_PROB_THRESHOLD', 0.55)
        self.enhanced_threshold = max(0.65, self.base_prob_threshold)  # 최소 65%

        logger.info(f"🚀 [Enhanced DL] 전략 엔진 초기화 (Threshold: {self.enhanced_threshold:.0%})")

    # ════════════════════════════════════════════════════════════════════
    # 📊 신호 생성 1: DL Momentum (딥러닝 기반 모멘텀)
    # ════════════════════════════════════════════════════════════════════

    def signal_dl_momentum(self, df: pd.DataFrame) -> Tuple[str, float, float]:
        """
        기존 딥러닝 로직 (개선)
        - 피처: return (1, 5), volatility, momentum (추가)
        """
        if len(df) < 20:
            return "none", 0.0, 0.0

        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values if 'volume' in df else np.ones(len(close))

        # 기술지표 계산
        ret_1 = (close[-1] - close[-2]) / close[-2]
        ret_5 = (close[-1] - close[-6]) / close[-6]
        ret_20 = (close[-1] - close[-20]) / close[-20]

        # ATR
        tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
        atr = np.mean(tr[-14:])
        volatility = atr / close[-1]

        # Momentum (ROC)
        roc = (close[-1] - close[-12]) / close[-12] if len(close) > 12 else 0

        # Volume ratio (최근 거래량이 평균보다 큼?)
        avg_vol = np.mean(volume[-20:])
        vol_ratio = volume[-1] / (avg_vol + 1e-9)

        # 수익률 가중합. sign 항을 쓰면 크기가 수익률(1e-3 규모)의 100배가 되어
        # "마지막 봉의 방향" 하나가 확률을 포화시킨다 — 넣지 않는다.
        score = (ret_1 * 0.25) + (ret_5 * 0.30) + (ret_20 * 0.15) + (roc * 0.20)

        # 확률 계산 (더 정교함)
        prob = 1.0 / (1.0 + math.exp(-score * 80))

        # 거래량 필터: 거래량 낮으면 확률 20% 감소
        if vol_ratio < 0.8:
            prob *= 0.8

        direction = "long" if prob > 0.5 else "short"
        confidence = abs(prob - 0.5) * 2  # 0~1 범위

        logger.debug(f"[DL_Momentum] ret_1={ret_1:.2%}, ret_5={ret_5:.2%}, "
                    f"roc={roc:.2%}, vol_ratio={vol_ratio:.2f}, prob={prob:.2%}")

        return direction, prob, confidence

    # ════════════════════════════════════════════════════════════════════
    # 📊 신호 생성 2: Mean Reversion (평균회귀)
    # ════════════════════════════════════════════════════════════════════

    def signal_mean_reversion(self, df: pd.DataFrame) -> Tuple[str, float, float]:
        """
        평균회귀 신호
        - 극단적 위치에서 중앙값으로의 수렴 가정
        """
        if len(df) < 50:
            return "none", 0.0, 0.0

        close = df['close'].values

        # 20일 SMA와의 거리
        sma_20 = np.mean(close[-20:])
        sma_50 = np.mean(close[-50:])
        distance_sma = (close[-1] - sma_20) / (sma_20 + 1e-9)

        # 보겐서 밴드 거리
        std_20 = np.std(close[-20:])
        bb_upper = sma_20 + (2 * std_20)
        bb_lower = sma_20 - (2 * std_20)

        # 현재가가 보겐서 밴드 상단/하단에서 얼마나 벗어났는가?
        if close[-1] > bb_upper:
            # 상단 극단 → 하락 신호 (Short)
            extremeness = (close[-1] - bb_upper) / (std_20 + 1e-9)
            prob = 0.3 + (min(extremeness * 0.15, 0.35))  # 30~65%
            direction = "short"
        elif close[-1] < bb_lower:
            # 하단 극단 → 상승 신호 (Long)
            extremeness = (bb_lower - close[-1]) / (std_20 + 1e-9)
            prob = 0.3 + (min(extremeness * 0.15, 0.35))
            direction = "long"
        else:
            return "none", 0.0, 0.0

        confidence = prob - 0.5  # 0~0.5 범위

        logger.debug(f"[MeanReversion] distance_sma={distance_sma:.2%}, "
                    f"extremeness={extremeness:.2f}, prob={prob:.2%}")

        return direction, prob, confidence

    # ════════════════════════════════════════════════════════════════════
    # 📊 신호 생성 3: Trend Following (추세 추종)
    # ════════════════════════════════════════════════════════════════════

    def signal_trend_following(self, df: pd.DataFrame) -> Tuple[str, float, float]:
        """
        추세 추종 신호
        - 단기/중기 추세 일치도 확인
        """
        if len(df) < 50:
            return "none", 0.0, 0.0

        close = df['close'].values
        high = df['high'].values
        low = df['low'].values

        # EMA 계산
        ema_10 = self._ema(close, 10)
        ema_20 = self._ema(close, 20)
        ema_50 = self._ema(close, 50)

        # 추세 판정
        if ema_10[-1] > ema_20[-1] > ema_50[-1]:
            # 상승 추세
            direction = "long"
            # 강도: 현재가가 EMA들 위에서 얼마나 떨어져 있는가?
            distance_pct = (close[-1] - ema_50[-1]) / (ema_50[-1] + 1e-9)
            strength = min(distance_pct * 2, 0.5)  # 0~0.5
            prob = 0.5 + strength

        elif ema_10[-1] < ema_20[-1] < ema_50[-1]:
            # 하락 추세
            direction = "short"
            distance_pct = (ema_50[-1] - close[-1]) / (ema_50[-1] + 1e-9)
            strength = min(distance_pct * 2, 0.5)
            prob = 0.5 + strength
        else:
            # 추세 없음 (혼합)
            return "none", 0.0, 0.0

        confidence = prob - 0.5

        logger.debug(f"[TrendFollowing] EMA_10={ema_10[-1]:.4f}, "
                    f"EMA_20={ema_20[-1]:.4f}, EMA_50={ema_50[-1]:.4f}, prob={prob:.2%}")

        return direction, prob, confidence

    # ════════════════════════════════════════════════════════════════════
    # 📊 신호 생성 4: Volatility Adaptive (변동성 적응)
    # ════════════════════════════════════════════════════════════════════

    def signal_volatility_adaptive(self, df: pd.DataFrame) -> Tuple[str, float, float]:
        """
        변동성 기반 신호
        - 높은 변동성 환경에서는 보수적, 낮은 변동성에서는 공격적
        - 변동성이 높아지면 평균회귀, 낮아지면 추세 신호
        """
        if len(df) < 30:
            return "none", 0.0, 0.0

        close = df['close'].values
        high = df['high'].values
        low = df['low'].values

        # 현재 변동성 (20일 기준)
        ret = np.diff(np.log(close[-20:]))
        volatility_recent = np.std(ret)

        # 과거 변동성 (평균)
        volatility_historical = np.std(np.diff(np.log(close[-100:])))\
             if len(close) > 100 else volatility_recent

        # 변동성 비율
        vol_ratio = volatility_recent / (volatility_historical + 1e-9)

        # High vol = 평균회귀 신호, Low vol = 추세 신호
        if vol_ratio > 1.5:
            # 고변동성: 평균회귀 (극단 값 회복)
            sma_20 = np.mean(close[-20:])
            if close[-1] > sma_20 * 1.02:
                direction = "short"
                prob = 0.4 + (vol_ratio - 1.5) * 0.15
            elif close[-1] < sma_20 * 0.98:
                direction = "long"
                prob = 0.4 + (vol_ratio - 1.5) * 0.15
            else:
                return "none", 0.0, 0.0
        else:
            # 저변동성: 추세추종 (모멘텀 유지)
            if close[-1] > np.mean(close[-5:]):
                direction = "long"
                prob = 0.55
            else:
                direction = "short"
                prob = 0.55

        confidence = abs(vol_ratio - 1.0) * 0.3

        logger.debug(f"[VolatilityAdaptive] vol_ratio={vol_ratio:.2f}, prob={prob:.2%}")

        return direction, prob, confidence

    # ════════════════════════════════════════════════════════════════════
    # 📊 신호 생성 5: Contrarian (역방향 매매) — 🆕 추가!
    # ════════════════════════════════════════════════════════════════════

    def signal_contrarian(self, df: pd.DataFrame) -> Tuple[str, float, float, str]:
        """
        역방향 신호 (Contrarian)
        - 극도로 극단적인 신호가 나온 직후, 그 반대 방향으로 급반전할 때
        - "과도한 상승 → 급하락" 패턴 감지
        """
        if len(df) < 10:
            return "none", 0.0, 0.0, ""

        close = df['close'].values

        # 최근 3봉 수익률
        ret_3 = [(close[i] - close[i-1]) / close[i-1] for i in range(-3, 0)]

        # 극도로 한쪽 방향인지 확인
        sum_ret = sum(ret_3)
        if sum(1 for r in ret_3 if r > 0) >= 2 and sum_ret > 0.03:
            # 3봉 연속 상승 + 3% 이상 → 역방향 (Short)
            # 근거: 과도한 상승은 조정이 나올 확률 높음
            direction = "short"
            prob = 0.45 + min(abs(sum_ret) * 5, 0.20)  # 45~65%
            reason = "Contrarian_Overbought"
        elif sum(1 for r in ret_3 if r < 0) >= 2 and sum_ret < -0.03:
            # 3봉 연속 하락 + 3% 이상 하락 → 역방향 (Long)
            direction = "long"
            prob = 0.45 + min(abs(sum_ret) * 5, 0.20)
            reason = "Contrarian_Oversold"
        else:
            return "none", 0.0, 0.0, ""

        confidence = prob - 0.45

        logger.debug(f"[Contrarian] sum_ret={sum_ret:.2%}, prob={prob:.2%}, "
                    f"reason={reason}")

        return direction, prob, confidence, reason

    # ════════════════════════════════════════════════════════════════════
    # 🔄 신호 통합 (Ensemble Voting)
    # ════════════════════════════════════════════════════════════════════

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Signal:
        """
        5가지 신호를 결합하여 최종 신호 생성
        - Voting 방식: 과반 이상이 같은 방향이면 신호 발생
        - Weighted average: 확률을 가중 평균
        """

        if df.empty or len(df) < 60:
            return Signal(symbol, "none", 0.0, 0.0, 0.0, "Enhanced DL", 0.0,
                         close=0.0, atr=0.0)

        current_price = float(df['close'].values[-1])
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values

        # ATR 계산
        tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
        atr = np.mean(tr[-14:]) if len(tr) >= 14 else (high[-1] - low[-1])

        # 📊 5가지 신호 생성
        signals = {}

        # 1. DL Momentum
        try:
            dir1, prob1, conf1 = self.signal_dl_momentum(df)
            signals['DL_Momentum'] = (dir1, prob1, conf1 * 0.2)  # 가중치 20%
        except Exception as e:
            logger.warning(f"DL_Momentum 계산 실패: {e}")
            signals['DL_Momentum'] = ("none", 0.0, 0.0)

        # 2. Mean Reversion
        try:
            dir2, prob2, conf2 = self.signal_mean_reversion(df)
            signals['MeanReversion'] = (dir2, prob2, conf2 * 0.15)  # 가중치 15%
        except Exception as e:
            logger.warning(f"MeanReversion 계산 실패: {e}")
            signals['MeanReversion'] = ("none", 0.0, 0.0)

        # 3. Trend Following
        try:
            dir3, prob3, conf3 = self.signal_trend_following(df)
            signals['TrendFollowing'] = (dir3, prob3, conf3 * 0.25)  # 가중치 25%
        except Exception as e:
            logger.warning(f"TrendFollowing 계산 실패: {e}")
            signals['TrendFollowing'] = ("none", 0.0, 0.0)

        # 4. Volatility Adaptive
        try:
            dir4, prob4, conf4 = self.signal_volatility_adaptive(df)
            signals['VolAdaptive'] = (dir4, prob4, conf4 * 0.15)  # 가중치 15%
        except Exception as e:
            logger.warning(f"VolAdaptive 계산 실패: {e}")
            signals['VolAdaptive'] = ("none", 0.0, 0.0)

        # 5. Contrarian (새로 추가!)
        try:
            result = self.signal_contrarian(df)
            if len(result) == 4:
                dir5, prob5, conf5, reason5 = result
                signals['Contrarian'] = (dir5, prob5, conf5 * 0.25)  # 가중치 25%
            else:
                signals['Contrarian'] = ("none", 0.0, 0.0)
        except Exception as e:
            logger.warning(f"Contrarian 계산 실패: {e}")
            signals['Contrarian'] = ("none", 0.0, 0.0)

        # 🔄 Voting 로직
        active_signals = {k: v for k, v in signals.items() if v[0] != "none"}

        if len(active_signals) == 0:
            return Signal(symbol, "none", current_price, 0.0, 0.0, "Enhanced DL", 0.0,
                         close=current_price, atr=float(atr),
                         reason="No_Active_Signals")

        # 가중 투표
        long_votes = sum(1 for v in active_signals.values() if v[0] == "long")
        short_votes = sum(1 for v in active_signals.values() if v[0] == "short")

        # 과반 이상 일치?
        if long_votes >= 2:
            direction = "long"
            avg_prob = np.mean([v[1] for v in active_signals.values() if v[0] == "long"])
        elif short_votes >= 2:
            direction = "short"
            avg_prob = np.mean([v[1] for v in active_signals.values() if v[0] == "short"])
        else:
            # 신호 상충 → 신호 미발생
            return Signal(symbol, "none", current_price, 0.0, 0.0, "Enhanced DL", 0.0,
                         close=current_price, atr=float(atr),
                         reason="Signal_Conflict")

        # Threshold 체크 (enhanced version)
        threshold = self.enhanced_threshold

        if avg_prob < threshold:
            return Signal(symbol, "none", current_price, 0.0, 0.0, "Enhanced DL", avg_prob,
                         close=current_price, atr=float(atr),
                         reason=f'Prob_Below_Threshold: {avg_prob:.1%} < {threshold:.0%}')

        # SL/TP 계산 (Enhanced version — ATR 기반, 동적 조정)
        sl_mult = self._get_dynamic_sl_mult(avg_prob, len(active_signals))
        tp_mult = self._get_dynamic_tp_mult(avg_prob, len(active_signals))

        if direction == "long":
            sl_price = current_price - (atr * sl_mult)
            tp_price = current_price + (atr * tp_mult)
        else:
            sl_price = current_price + (atr * sl_mult)
            tp_price = current_price - (atr * tp_mult)

        # 신호 출처 기록
        signal_sources = [k for k, v in active_signals.items() if v[0] == direction]

        logger.info(f"🎯 [Enhanced DL] {symbol} {direction.upper()} | "
                   f"Prob: {avg_prob:.2%} | Votes: {long_votes}L vs {short_votes}S | "
                   f"Sources: {','.join(signal_sources)} | "
                   f"SL: {sl_price:.4f} TP: {tp_price:.4f}")

        return Signal(
            symbol=symbol,
            direction=direction,
            price=current_price,
            sl_price=sl_price,
            tp_price=tp_price,
            regime="Enhanced_DL",
            prob=avg_prob,
            strength=avg_prob * 100.0,
            reason='Ensemble_Signal',
            signal_sources=signal_sources,
            confidence=avg_prob - 0.5,
            multi_timeframe=len(active_signals) >= 3,
            # Trader compatibility
            close=current_price,
            atr=float(atr),
            swing_sl_price=sl_price,
            tp1_price=tp_price,
        )

    # ════════════════════════════════════════════════════════════════════
    # 🛠️ 보조 함수들
    # ════════════════════════════════════════════════════════════════════

    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """EMA 계산"""
        if len(data) < period:
            return np.array([data[-1]] * len(data))

        ema = np.zeros(len(data))
        multiplier = 2 / (period + 1)
        ema[0] = np.mean(data[:period])

        for i in range(1, len(data)):
            ema[i] = data[i] * multiplier + ema[i-1] * (1 - multiplier)

        return ema

    def _get_dynamic_sl_mult(self, prob: float, num_signals: int) -> float:
        """
        동적 SL 배수
        - 확률이 높고, 여러 신호가 일치하면 더 타이트
        """
        base_mult = 2.0
        prob_adj = (prob - 0.5) * 2  # 0.5~1.0 → 0~1.0
        signal_adj = num_signals / 5.0  # 신호 수가 많을수록 타이트

        mult = base_mult * (1 - prob_adj * 0.3) * (1 - signal_adj * 0.2)
        return max(mult, 1.0)  # 최소 1.0배

    def _get_dynamic_tp_mult(self, prob: float, num_signals: int) -> float:
        """
        동적 TP 배수
        - 확률이 높고, 여러 신호가 일치하면 더 공격적
        """
        base_mult = 4.0
        prob_adj = (prob - 0.5) * 2
        signal_adj = num_signals / 5.0

        mult = base_mult * (1 + prob_adj * 0.5) * (1 + signal_adj * 0.3)
        return mult


# Backward compatibility
StrategyEngine = EnhancedStrategyEngine
