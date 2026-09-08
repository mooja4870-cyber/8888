import numpy as np
import pandas as pd
import math

def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Welles Wilder ADX"""
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    atr = pd.Series(tr).ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan))
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan))
    
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx.fillna(20.0)

def compute_ker(series: pd.Series, period: int = 20) -> pd.Series:
    """Kaufman Efficiency Ratio"""
    change = (series - series.shift(period)).abs()
    volatility = series.diff().abs().rolling(period).sum()
    ker = change / (volatility + 1e-10)
    return ker.fillna(0.2)

def evaluate_profitability_booster(df: pd.DataFrame, direction: str, funding_rate: float = 0.0, cfg: dict = None) -> tuple:
    """
    8401 5대 퀀트 수익성부스터 평가기
    반환: (통과여부: bool, 부스터보너스점수: float, 부스터사유: str, 지표상세: dict)
    """
    if df is None or len(df) < 35:
        return True, 0.0, "데이터 부족 (기본 통과)", {}
        
    cfg = cfg or {}
    use_booster = bool(cfg.get("USE_PROFIT_BOOSTER", True))
    if not use_booster:
        return True, 0.0, "부스터 비활성", {}

    max_adx = float(cfg.get("BOOSTER_MAX_ADX", 28.0))
    max_ker = float(cfg.get("BOOSTER_MAX_KER", 0.38))
    vol_spike_mult = float(cfg.get("BOOSTER_VOL_SPIKE_MULT", 1.3))
    min_wick_pct = float(cfg.get("BOOSTER_MIN_WICK_PCT", 0.20)) # 20% 이상 꼬리
    
    c = df['close']
    h = df['high']
    l = df['low']
    o = df['open']
    v = df['volume']
    
    # 1. 지표 산출
    adx_series = compute_adx(df, 14)
    ker_series = compute_ker(c, 20)
    vol_ma20 = v.rolling(20).mean()
    
    curr_c = float(c.iloc[-1])
    curr_h = float(h.iloc[-1])
    curr_l = float(l.iloc[-1])
    curr_o = float(o.iloc[-1])
    curr_v = float(v.iloc[-1])
    curr_v_ma = float(vol_ma20.iloc[-1]) if not np.isnan(vol_ma20.iloc[-1]) else curr_v
    
    curr_adx = float(adx_series.iloc[-1])
    curr_ker = float(ker_series.iloc[-1])
    
    candle_range = max(curr_h - curr_l, 1e-10)
    lower_wick = max(min(curr_o, curr_c) - curr_l, 0.0) / candle_range
    upper_wick = max(curr_h - max(curr_o, curr_c), 0.0) / candle_range
    vol_ratio = curr_v / max(curr_v_ma, 1e-10)
    
    metrics = {
        "adx": round(curr_adx, 1),
        "ker": round(curr_ker, 3),
        "vol_ratio": round(vol_ratio, 2),
        "lower_wick": round(lower_wick * 100, 1),
        "upper_wick": round(upper_wick * 100, 1),
        "funding_rate": funding_rate,
        "is_regime_ok": True,
        "is_vol_climax": False,
        "is_wick_rejected": False,
        "is_funding_squeeze": False,
    }
    
    # ── [부스터 1: 국면 필터 (Regime Gate)] ──
    # ADX > 28 또는 KER > 0.38 인 강한 추세장에서는 역추세 진입 차단 (밴드워킹 방어)
    if curr_adx > max_adx or curr_ker > max_ker:
        metrics["is_regime_ok"] = False
        reason = f"🛑 [부스터 차단] 강한 추세장 밴드워킹 휩쏘 방어 (ADX {curr_adx:.1f}>{max_adx:.0f} or KER {curr_ker:.2f}>{max_ker:.2f})"
        return False, 0.0, reason, metrics
        
    score_bonus = 0.0
    booster_tags = []
    
    # ── [부스터 2: 거래량 클라이맥스 & 꼬리 거절 (Volume & Wick)] ──
    if direction == "long":
        if vol_ratio >= vol_spike_mult:
            metrics["is_vol_climax"] = True
            score_bonus += 10.0
            booster_tags.append(f"거래량스파이크({vol_ratio:.1f}x)")
        if lower_wick >= min_wick_pct:
            metrics["is_wick_rejected"] = True
            score_bonus += 10.0
            booster_tags.append(f"아래꼬리지지({lower_wick*100:.0f}%)")
            
        # ── [부스터 3: OKX 펀딩비 숏 스퀴즈 알파] ──
        if funding_rate <= -0.00015:  # -0.015% 이하
            metrics["is_funding_squeeze"] = True
            score_bonus += 15.0
            booster_tags.append(f"숏스퀴즈펀딩({funding_rate*100:.3f}%)")
        elif funding_rate >= 0.0004:   # +0.04% 이상 극단적 롱 과열
            score_bonus -= 10.0        # 역방향 감점
            
    elif direction == "short":
        if vol_ratio >= vol_spike_mult:
            metrics["is_vol_climax"] = True
            score_bonus += 10.0
            booster_tags.append(f"거래량스파이크({vol_ratio:.1f}x)")
        if upper_wick >= min_wick_pct:
            metrics["is_wick_rejected"] = True
            score_bonus += 10.0
            booster_tags.append(f"윗꼬리저항({upper_wick*100:.0f}%)")
            
        # ── [부스터 3: OKX 펀딩비 롱 스퀴즈 덤핑 알파] ──
        if funding_rate >= 0.00025:   # +0.025% 이상
            metrics["is_funding_squeeze"] = True
            score_bonus += 15.0
            booster_tags.append(f"롱스퀴즈펀딩({funding_rate*100:.3f}%)")
        elif funding_rate <= -0.0003:  # -0.03% 이하 극단적 숏 과열
            score_bonus -= 10.0        # 역방향 감점

    # 최소 1개 이상의 반등 컨펌(거래량 or 꼬리 or 펀딩비) 필요 여부
    require_confirmation = bool(cfg.get("BOOSTER_REQUIRE_CONFIRMATION", True))
    if require_confirmation and not (metrics["is_vol_climax"] or metrics["is_wick_rejected"] or metrics["is_funding_squeeze"]):
        # 캔들이 꽉 찬 장대봉(Marubozu)으로 밴드를 찢고 나가는 경우 진입 유보
        reason = f"⚠️ [부스터 유보] 반등 컨펌 미달 (장대봉 이탈: 꼬리 {lower_wick*100:.0f}%/{upper_wick*100:.0f}%, 볼륨 {vol_ratio:.1f}x)"
        return False, 0.0, reason, metrics
        
    tag_str = ", ".join(booster_tags) if booster_tags else "정상박스권"
    reason = f"🚀 [부스터 가동] {tag_str} (ADX={curr_adx:.1f}, KER={curr_ker:.2f})"
    return True, score_bonus, reason, metrics

if __name__ == "__main__":
    print("Booster logic compiled successfully!")
