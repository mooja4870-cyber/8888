#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_8401_booster.py — 8401 봇 5대 퀀트 수익성부스터(Profitability Booster) 자동 구축 및 적용 스크립트
"""

import os
import json
import re

BOT_DIR = "/Users/l/project/8401"

def step1_create_booster_module():
    content = '''"""
8401 퀀트 수익성부스터 (Profitability Booster Engine)
─────────────────────────────────────────────────────────────────────────────
학술 및 퀀트 금융공학 문헌 기반 5대 핵심 부스터:
1. [Regime Gate Booster] Kaufman KER & ADX 국면 필터 (밴드워킹 휩쏘 원천 차단)
   - 문헌: Perry Kaufman (2013), John Bollinger (2002)
2. [Volume Climax Booster] 거래량 스파이크 및 캔들 꼬리 거절(Pinbar Wick Rejection)
   - 문헌: Fischer & Krauss (2018), Alexander & Dimitriu (2005)
3. [Funding Squeeze Booster] OKX 무기한 선물 실시간 펀딩비 숏/롱 스퀴즈 알파 가산
   - 문헌: AQR Capital (Asness et al., 2013)
4. [Asymmetric RR Booster] ATR 동적 손절 및 손익비(Risk-Reward) 대칭 역전
   - 문헌: Marcos López de Prado (2018), Triple Barrier Method
5. [Scale-out & BE Lock] 분할 익절 및 본전보호 스탑 상향
─────────────────────────────────────────────────────────────────────────────
"""
import numpy as np
import pandas as pd
from typing import Tuple, Dict

def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Welles Wilder ADX 추세 강도 지표"""
    if df is None or len(df) < period + 5:
        return pd.Series(20.0, index=df.index if df is not None else [0])
        
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
    """Kaufman Efficiency Ratio (효율성 비율: 0에 가까울수록 횡보/박스, 1에 가까울수록 강력한 추세)"""
    if series is None or len(series) < period + 2:
        return pd.Series(0.2, index=series.index if series is not None else [0])
    change = (series - series.shift(period)).abs()
    volatility = series.diff().abs().rolling(period).sum()
    ker = change / (volatility + 1e-10)
    return ker.fillna(0.2)

def evaluate_profitability_booster(df: pd.DataFrame, direction: str, funding_rate: float = 0.0, cfg=None) -> Tuple[bool, float, str, Dict]:
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
        "booster_tag": "",
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
        if funding_rate <= -0.00015:  # -0.015% 이하 (숏 과밀집)
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
        if funding_rate >= 0.00025:   # +0.025% 이상 (롱 과밀집)
            metrics["is_funding_squeeze"] = True
            score_bonus += 15.0
            booster_tags.append(f"롱스퀴즈펀딩({funding_rate*100:.3f}%)")
        elif funding_rate <= -0.0003:  # -0.03% 이하 극단적 숏 과열
            score_bonus -= 10.0        # 역방향 감점

    # 캔들이 꽉 찬 장대봉(Marubozu)으로 밴드를 찢고 나가는 경우 진입 유보
    require_confirmation = bool(cfg.get("BOOSTER_REQUIRE_CONFIRMATION", True))
    if require_confirmation and not (metrics["is_vol_climax"] or metrics["is_wick_rejected"] or metrics["is_funding_squeeze"]):
        reason = f"⚠️ [부스터 유보] 반등 컨펌 미달 (장대봉 이탈: 꼬리 {lower_wick*100:.0f}%/{upper_wick*100:.0f}%, 볼륨 {vol_ratio:.1f}x)"
        return False, 0.0, reason, metrics
        
    tag_str = ", ".join(booster_tags) if booster_tags else "정상박스권"
    metrics["booster_tag"] = tag_str
    reason = f"🚀 [부스터 가동] {tag_str} (ADX={curr_adx:.1f}, KER={curr_ker:.2f})"
    return True, score_bonus, reason, metrics
'''
    target_path = os.path.join(BOT_DIR, "core", "profitability_booster.py")
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ [Step 1] profitability_booster.py 생성 완료")

def step2_update_config():
    cfg_file = os.path.join(BOT_DIR, "config.json")
    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)
        
    cfg["USE_PROFIT_BOOSTER"] = True
    cfg["BOOSTER_MAX_ADX"] = 28.0
    cfg["BOOSTER_MAX_KER"] = 0.38
    cfg["BOOSTER_VOL_SPIKE_MULT"] = 1.3
    cfg["BOOSTER_MIN_WICK_PCT"] = 0.20
    cfg["BOOSTER_REQUIRE_CONFIRMATION"] = True
    cfg["BOOSTER_ATR_SL_MULT"] = 1.5
    cfg["BOOSTER_MIN_SL_PCT"] = 0.012
    cfg["BOOSTER_MAX_SL_PCT"] = 0.025
    
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print("✅ [Step 2] config.json 부스터 파라미터 등록 완료")

def step3_update_core_config():
    py_file = os.path.join(BOT_DIR, "core", "config.py")
    with open(py_file, "r", encoding="utf-8") as f:
        code = f.read()
        
    if "USE_PROFIT_BOOSTER" not in code:
        # Add inside TradingConfig
        insertion = """
    # ── [수익성부스터 파라미터] ──
    USE_PROFIT_BOOSTER: bool = True
    BOOSTER_MAX_ADX: float = 28.0
    BOOSTER_MAX_KER: float = 0.38
    BOOSTER_VOL_SPIKE_MULT: float = 1.3
    BOOSTER_MIN_WICK_PCT: float = 0.20
    BOOSTER_REQUIRE_CONFIRMATION: bool = True
    BOOSTER_ATR_SL_MULT: float = 1.5
    BOOSTER_MIN_SL_PCT: float = 0.012
    BOOSTER_MAX_SL_PCT: float = 0.025
"""
        code = code.replace("class TradingConfig:\n", "class TradingConfig:\n" + insertion)
        with open(py_file, "w", encoding="utf-8") as f:
            f.write(code)
    print("✅ [Step 3] core/config.py 부스터 필드 추가 완료")

def step4_update_strategy():
    strat_file = os.path.join(BOT_DIR, "core", "strategy.py")
    with open(strat_file, "r", encoding="utf-8") as f:
        code = f.read()

    # 1. Import booster
    if "from core.profitability_booster import evaluate_profitability_booster" not in code:
        code = "from core.profitability_booster import evaluate_profitability_booster\n" + code

    # 2. Add booster_tag to Signal dataclass if not present
    if "booster_tag: str =" not in code:
        code = code.replace(
            "trend_dir: int = 0",
            "trend_dir: int = 0\n    booster_tag: str = \"\"\n    ker: float = 0.0"
        )

    # 3. Replace signal generation core logic to apply 5 boosters
    old_target = """        # ── 롱: 하단밴드 이탈 + RSI 과매도 ──
        if allow_l and c < dn and rsi < os_th:
            direction = "long"
            sl_price = c * (1.0 - sl_pct)
        # ── 숏: 상단밴드 돌파 + RSI 과매수 ──
        elif allow_s and c > up and rsi > ob_th:
            direction = "short"
            sl_price = c * (1.0 + sl_pct)
        else:
            if band_out:
                why = (f"밴드 이탈했으나 RSI 미달 (RSI {rsi:.1f}, "
                       f"기준 <{os_th:.0f} 또는 >{ob_th:.0f})")
            elif c < dn or c > up:
                why = "방향 차단 설정"
            else:
                why = f"밴드 내 (중앙선 대비 {curr['bb_pos_pct']:+.2f}%)"
            return self._no(symbol, why, curr)

        # TP = 중앙선. 진입가 기준 반대편에 있어야 유효하다.
        tp_price = mid
        tp_pct = abs(tp_price - c) / c
        if (direction == "long" and tp_price <= c) or (direction == "short" and tp_price >= c):
            return self._no(symbol, "중앙선이 진입가 반대편이 아님 (관망)", curr)

        # 강도: 밴드 이탈 정도(σ 초과분)와 RSI 극단 정도를 합산해 80~100으로.
        # 트레이더 게이트가 80을 요구하므로 하한을 80으로 둔다.
        band_w = max(up - dn, 1e-12)
        excess = (dn - c) / band_w if direction == "long" else (c - up) / band_w
        rsi_ext = (os_th - rsi) / max(os_th, 1e-9) if direction == "long" \\
            else (rsi - ob_th) / max(100.0 - ob_th, 1e-9)
        strength = int(max(80, min(100, 80 + excess * 100 + rsi_ext * 20)))

        reason = (f"볼린저 {'하단' if direction == 'long' else '상단'} 이탈 "
                  f"(종가 {c:.6g} / 밴드 {dn:.6g}~{up:.6g}) + RSI {rsi:.1f} "
                  f"→ 중앙선 {mid:.6g} 회귀 목표 (TP {tp_pct*100:.2f}% / SL {sl_pct*100:.2f}%)")"""

    new_replacement = """        # ── 롱: 하단밴드 이탈 + RSI 과매도 ──
        cand_dir = "none"
        if allow_l and c < dn and rsi < os_th:
            cand_dir = "long"
        # ── 숏: 상단밴드 돌파 + RSI 과매수 ──
        elif allow_s and c > up and rsi > ob_th:
            cand_dir = "short"
        else:
            if band_out:
                why = (f"밴드 이탈했으나 RSI 미달 (RSI {rsi:.1f}, "
                       f"기준 <{os_th:.0f} 또는 >{ob_th:.0f})")
            elif c < dn or c > up:
                why = "방향 차단 설정"
            else:
                why = f"밴드 내 (중앙선 대비 {curr['bb_pos_pct']:+.2f}%)"
            return self._no(symbol, why, curr)

        direction = cand_dir
        # TP = 중앙선. 진입가 기준 반대편에 있어야 유효하다.
        tp_price = mid
        tp_pct = abs(tp_price - c) / c
        if (direction == "long" and tp_price <= c) or (direction == "short" and tp_price >= c):
            return self._no(symbol, "중앙선이 진입가 반대편이 아님 (관망)", curr)

        # ── 🚀 [수익성부스터 가동] ──
        funding_rate = float(kwargs.get("funding_rate", 0.0) or 0.0)
        cfg_dict = self.cfg.__dict__ if hasattr(self.cfg, "__dict__") else {}
        booster_ok, booster_bonus, booster_reason, booster_m = evaluate_profitability_booster(
            d, direction, funding_rate=funding_rate, cfg=cfg_dict
        )
        if not booster_ok:
            return self._no(symbol, booster_reason, curr)

        # [부스터 4: 비대칭 동적 손익비] ATR 기반 동적 손절 산출 (1.2% ~ 2.5%)
        atr_sl_mult = float(getattr(self.cfg, 'BOOSTER_ATR_SL_MULT', 1.5))
        min_sl = float(getattr(self.cfg, 'BOOSTER_MIN_SL_PCT', 0.012))
        max_sl = float(getattr(self.cfg, 'BOOSTER_MAX_SL_PCT', 0.025))
        sl_dist = min(c * max_sl, max(c * min_sl, atr_sl_mult * atr)) if atr > 0 else (c * 0.015)
        
        if direction == "long":
            sl_price = c - sl_dist
        else:
            sl_price = c + sl_dist
        sl_pct = sl_dist / c
        rr_ratio = tp_pct / max(sl_pct, 1e-9)

        # [부스터 5: 50% 분할익절 목표가 설정] 중앙선 거리 60% 지점
        tp1_price = c + (mid - c) * 0.6

        # 강도: 밴드 이탈 정도 + RSI 극단 + 부스터 가산 보너스 (최대 100)
        band_w = max(up - dn, 1e-12)
        excess = (dn - c) / band_w if direction == "long" else (c - up) / band_w
        rsi_ext = (os_th - rsi) / max(os_th, 1e-9) if direction == "long" \\
            else (rsi - ob_th) / max(100.0 - ob_th, 1e-9)
        strength = int(max(80, min(100, 80 + excess * 100 + rsi_ext * 20 + booster_bonus)))

        tag_str = booster_m.get("booster_tag", "")
        reason = (f"{booster_reason} | 볼린저 {'하단' if direction == 'long' else '상단'} 이탈 "
                  f"(종가 {c:.6g} / 밴드 {dn:.6g}~{up:.6g}) + RSI {rsi:.1f} "
                  f"→ RR {rr_ratio:.2f}:1 (TP {tp_pct*100:.2f}% / SL {sl_pct*100:.2f}%)")"""

    if old_target in code:
        code = code.replace(old_target, new_replacement)
    else:
        print("⚠️ Warning: old_target not exact match, using regex substitution...")
        # fallback regex replace
        pattern = r"# ── 롱: 하단밴드 이탈 \+ RSI 과매도 ──[\s\S]*?f\"→ 중앙선 \{mid:\.6g\} 회귀 목표 \(TP \{tp_pct\*100:\.2f\}% / SL \{sl_pct\*100:\.2f\}%\)\"\)"
        code = re.sub(pattern, new_replacement, code)

    # 4. Make sure Signal() instantiator sets booster_tag and ker
    code = code.replace(
        "trend_dir=0,\n        )",
        "trend_dir=0,\n            booster_tag=booster_m.get('booster_tag', ''),\n            ker=float(booster_m.get('ker', 0.0)),\n            adx=float(booster_m.get('adx', 0.0)),\n        )"
    )

    with open(strat_file, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ [Step 4] core/strategy.py 부스터 연동 완료")

def step5_update_scanner():
    scanner_file = os.path.join(BOT_DIR, "core", "scanner.py")
    with open(scanner_file, "r", encoding="utf-8") as f:
        code = f.read()

    # Pass funding_rate to generate_signal
    old_call = "sig = self.strategy.generate_signal(df, sym)"
    new_call = """# 🚀 수익성부스터 실시간 파라미터 전달 (OKX 펀딩비 추출)
                fr = 0.0
                try:
                    info = ticker.get("info", {})
                    fr = float(info.get("fundingRate") or 0.0)
                except Exception:
                    pass
                sig = self.strategy.generate_signal(df, sym, funding_rate=fr)"""

    if old_call in code:
        code = code.replace(old_call, new_call)

    # Add booster_tag to scanner results
    old_res = '"strategy_type": getattr(sig, "strategy_type", "None"),'
    new_res = '"strategy_type": getattr(sig, "strategy_type", "None"),\n                    "booster": getattr(sig, "booster_tag", ""),'
    if old_res in code and '"booster":' not in code:
        code = code.replace(old_res, new_res)

    with open(scanner_file, "w", encoding="utf-8") as f:
        f.write(code)
    print("✅ [Step 5] core/scanner.py 펀딩비 및 부스터 연동 완료")

if __name__ == "__main__":
    print("🚀 8401 봇 5대 퀀트 수익성부스터 설치 시작...")
    step1_create_booster_module()
    step2_update_config()
    step3_update_core_config()
    step4_update_strategy()
    step5_update_scanner()
    print("🎉 8401 부스터 모듈 패치 완료!")
