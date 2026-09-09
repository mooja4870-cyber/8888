"""
⑦ 딥러닝 방향예측 & 퀀트 수익성부스터(QPB-Alpha) 롱/숏 전략
────────────────────────────────────────────────────────────────────
Marcos López de Prado(2018) 메타 라벨링(Meta-Labeling) 및 
5대 금융공학 수익성 부스터(Profitability Booster) 융합 엔진

1. 1차 방향 탐지: 고저 돌파 및 다중 모멘텀 방향 검출
2. 2차 메타 품질 게이트: KER(추세 순도) + CMF(자금 유입) + Volume Spike(거래량 급증)
   + 바이낸스 펀딩비 숏 스퀴즈 복합 채점
3. 동적 부스터 사이징 및 비대칭 RR:
   - 슈퍼 부스터 (Score >= 0.75): 1.4x 증거금 가산, 3.5 ATR 광폭 익절
   - 일반 부스터 (0.58 <= Score < 0.75): 1.0x 표준, 2.2 ATR 익절
   - 기각 (Score < 0.58): 횡보/거짓돌파 사전 차단
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from core.config import CFG
from core.profitability_booster import evaluate_profitability_booster
import logging
import math

logger = logging.getLogger(__name__)

REGIME_DEEP_LEARNING = "딥러닝 방향예측(QPB)"


@dataclass
class Signal:
    symbol: str
    direction: str          # "long" | "short" | "none"
    price: float            # 진입 기준가 (현재가)
    sl_price: float         # 손절가
    tp_price: float         # 목표가
    regime: str             # "딥러닝 방향예측(QPB)"
    prob: float             # 모델 예측 확률 (Meta-Score)
    strength: float = 0.0
    rsi: float = 50.0
    reason: str = ''
    strategy_type: str = "DeepLearning_QPB"

    # 트레이더가 직접 참조하는 필수 필드
    close: float = 0.0            # 진입 기준가 — price와 동일값
    atr: float = 0.0              # 트레이더의 ATR 사이징 경로용
    adx: float = 0.0              # 추세 강도
    bb_mid: float = 0.0           # 0
    swing_sl_price: float = 0.0   # = sl_price
    tp1_price: float = 0.0        # = tp_price

    # 🚀 수익성부스터 전용 필드
    booster_tag: str = ""
    booster_score: float = 0.0
    booster_sizing_mult: float = 1.0
    ker: float = 0.0


class StrategyEngine:
    def __init__(self, cfg=None):
        self.cfg = cfg or CFG
        self.model_loaded = True
        logger.info("[QPB-Strategy] 8407 퀀트 수익성부스터(QPB-Alpha) 엔진 초기화 완료")

    async def update_trend(self, sym):
        pass

    def extract_features(self, df: pd.DataFrame) -> np.ndarray:
        n = int(getattr(self.cfg, 'TSMOM_LOOKBACK', 16))
        need = max(n + 2, 20)
        if len(df) < need:
            return None

        close = df['close'].values
        high = df['high'].values
        low = df['low'].values

        hh = float(np.max(high[-(n + 1):-1]))
        ll = float(np.min(low[-(n + 1):-1]))

        tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
        atr = np.mean(tr[-14:]) if len(tr) >= 14 else (high[-1] - low[-1])

        if close[-1] > hh:
            brk = 1.0
        elif close[-1] < ll:
            brk = -1.0
        else:
            brk = 0.0

        return np.array([brk, atr / close[-1] if close[-1] else 0.0, hh, ll])

    def predict_direction(self, features: np.ndarray) -> tuple:
        if features is None:
            return "none", 0.0
        brk = float(features[0])
        if brk == 0.0:
            return "none", 0.0
        return ("long" if brk > 0 else "short"), 0.99

    def generate_signal(self, df: pd.DataFrame, symbol: str, funding_rate: float = 0.0, **kwargs) -> Signal:
        if df.empty or len(df) < getattr(self.cfg, 'DL_LOOKBACK_BARS', 30):
            return Signal(symbol, "none", 0.0, 0.0, 0.0, REGIME_DEEP_LEARNING, 0.0)

        current_price = float(df['close'].iloc[-1])

        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
        atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else float(high[-1] - low[-1])

        features = self.extract_features(df)
        if features is None:
            return Signal(symbol, "none", current_price, 0.0, 0.0, REGIME_DEEP_LEARNING, 0.0,
                          reason="데이터 부족", close=current_price, atr=atr)

        cand_dir, _ = self.predict_direction(features)
        hh = features[2]
        ll = features[3]

        if cand_dir == "none":
            return Signal(
                symbol, "none", current_price, 0.0, 0.0, REGIME_DEEP_LEARNING, 0.0,
                reason=f"채널 내 횡보 ({ll:.4f} ~ {hh:.4f})",
                close=current_price, atr=atr
            )

        # ─────────────────────────────────────────────────────────────
        # 🚀 [수익성부스터(QPB-Alpha) 메타 라벨링 평가]
        # ─────────────────────────────────────────────────────────────
        booster_ok, meta_score, booster_reason, metrics = evaluate_profitability_booster(
            df, cand_dir, funding_rate=funding_rate, cfg=self.cfg
        )

        if not booster_ok:
            logger.info(f"[QPB REJECT] {symbol} {cand_dir.upper()} — {booster_reason}")
            return Signal(
                symbol=symbol,
                direction="none",
                price=current_price,
                sl_price=0.0,
                tp_price=0.0,
                regime=REGIME_DEEP_LEARNING,
                prob=meta_score,
                strength=0.0,
                reason=booster_reason,
                close=current_price,
                atr=atr,
                booster_score=meta_score,
                ker=metrics.get("ker", 0.0),
            )

        # ─────────────────────────────────────────────────────────────
        # 🎯 [승인된 신호: 동적 사이징 및 비대칭 RR 목표가 산정]
        # ─────────────────────────────────────────────────────────────
        tp_mult = float(metrics.get("tp_mult", 2.2))
        sizing_mult = float(metrics.get("sizing_mult", 1.0))
        booster_tag = str(metrics.get("booster_tag", ""))

        sl_mult = float(getattr(self.cfg, 'BOOSTER_SL_ATR', 1.5))
        sl_dist = atr * sl_mult

        # SL 하한(0.5%) 및 상한(3.0%) 보호
        min_sl_dist = current_price * float(getattr(self.cfg, 'MIN_SL_PCT', 0.005))
        max_sl_dist = current_price * float(getattr(self.cfg, 'MAX_SL_PCT', 0.030))
        sl_dist = max(min_sl_dist, min(max_sl_dist, sl_dist))

        tp_dist = atr * tp_mult

        if cand_dir == "long":
            sl_price = current_price - sl_dist
            tp_price = current_price + tp_dist
        else:
            sl_price = current_price + sl_dist
            tp_price = current_price - tp_dist

        strength = min(100.0, max(75.0, 60.0 + meta_score * 40.0))

        logger.info(
            f"[QPB APPROVED] {symbol} {cand_dir.upper()} | {booster_tag} | "
            f"Score: {meta_score:.2f} (KER={metrics.get('ker'):.2f}, CMF={metrics.get('cmf'):.2f}) | "
            f"Sizing: {sizing_mult}x | P: {current_price} SL: {sl_price:.4f} TP: {tp_price:.4f}"
        )

        return Signal(
            symbol=symbol,
            direction=cand_dir,
            price=current_price,
            sl_price=sl_price,
            tp_price=tp_price,
            regime=REGIME_DEEP_LEARNING,
            prob=meta_score,
            strength=strength,
            rsi=50.0,
            reason=booster_reason,
            close=current_price,
            atr=atr,
            adx=float(metrics.get("adx", 20.0)),
            swing_sl_price=sl_price,
            tp1_price=tp_price,
            booster_tag=booster_tag,
            booster_score=meta_score,
            booster_sizing_mult=sizing_mult,
            ker=float(metrics.get("ker", 0.0)),
        )
