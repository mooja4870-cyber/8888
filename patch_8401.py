import re

filepath = "/Users/l/project/8401/core/strategy.py"
with open(filepath, "r") as f:
    content = f.read()

# Chunk 1: calculate_indicators
old_1 = """        # ATR (트레이더의 사이징·트레일링이 sig.atr을 직접 참조한다)
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        d['atr'] = tr.ewm(alpha=1 / atr_p, adjust=False).mean()
        return d"""
new_1 = """        # ATR (트레이더의 사이징·트레일링이 sig.atr을 직접 참조한다)
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        d['atr'] = tr.ewm(alpha=1 / atr_p, adjust=False).mean()

        # [NEW] 꼬리 비율 (Wick Ratio) — 유동성 사냥용
        d['candle_len'] = high - low
        d['lower_wick'] = d[['open', 'close']].min(axis=1) - low
        d['upper_wick'] = high - d[['open', 'close']].max(axis=1)
        d['wick_ratio_long'] = np.where(d['candle_len'] > 0, d['lower_wick'] / d['candle_len'], 0.0)
        d['wick_ratio_short'] = np.where(d['candle_len'] > 0, d['upper_wick'] / d['candle_len'], 0.0)

        return d"""

# Chunk 2: generate_signal conditions
old_2 = """        # ── 롱: 하단밴드 이탈 + RSI 과매도 ──
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
            return self._no(symbol, "중앙선이 진입가 반대편이 아님 (관망)", curr)"""
new_2 = """        # ── 롱: 꼬리 70% 이상 + RSI 과매도 ──
        cand_dir = "none"
        if allow_l and curr['wick_ratio_long'] >= 0.70 and rsi <= os_th:
            cand_dir = "long"
        # ── 숏: 위꼬리 70% 이상 + RSI 과매수 ──
        elif allow_s and curr['wick_ratio_short'] >= 0.70 and rsi >= ob_th:
            cand_dir = "short"
        else:
            return self._no(symbol, f"진입 조건 미달 (RSI:{rsi:.1f}, WickL:{curr['wick_ratio_long']:.2f}, WickS:{curr['wick_ratio_short']:.2f})", curr)

        direction = cand_dir
        # 고승률 타점을 위해 SL=1.0x ATR, TP=3.0x ATR 하드코딩 적용 (백테스트 최적화값)
        sl_mult = 1.0
        tp_mult = 3.0
        
        if direction == "long":
            sl_price = c - (atr * sl_mult)
            tp_price = c + (atr * tp_mult)
        else:
            sl_price = c + (atr * sl_mult)
            tp_price = c - (atr * tp_mult)
            
        tp_pct = abs(tp_price - c) / c"""

# Chunk 3: calculate SL/TP and logs
old_3 = """        # [부스터 4: 비대칭 동적 손익비] ATR 기반 동적 손절 산출 (1.2% ~ 2.5%)
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
        rsi_ext = (os_th - rsi) / max(os_th, 1e-9) if direction == "long" \
            else (rsi - ob_th) / max(100.0 - ob_th, 1e-9)
        strength = int(max(80, min(100, 80 + excess * 100 + rsi_ext * 20 + booster_bonus)))

        tag_str = booster_m.get("booster_tag", "")
        reason = (f"{booster_reason} | 볼린저 {'하단' if direction == 'long' else '상단'} 이탈 "
                  f"(종가 {c:.6g} / 밴드 {dn:.6g}~{up:.6g}) + RSI {rsi:.1f} "
                  f"→ RR {rr_ratio:.2f}:1 (TP {tp_pct*100:.2f}% / SL {sl_pct*100:.2f}%)")

        logger.info(f"[BB-MR] {symbol} {direction.upper()} | 종가 {c:.6g} "
                    f"| 밴드 {dn:.6g}~{up:.6g} | RSI {rsi:.1f} "
                    f"| TP {mid:.6g}({tp_pct*100:.2f}%) SL {sl_price:.6g}({sl_pct*100:.2f}%)")"""
new_3 = """        # [부스터 오버라이드] 백테스트 골든 파라미터 강제 주입
        sl_dist = atr * sl_mult
        sl_pct = sl_dist / c
        rr_ratio = tp_pct / max(sl_pct, 1e-9)

        # TP1(부분익절)을 TP의 50% 지점으로 설정
        tp1_price = c + (tp_price - c) * 0.5

        # 강도: 꼬리 길이 + 극단적 RSI + 부스터 가산 보너스 (최대 100)
        wick_val = curr['wick_ratio_long'] if direction == "long" else curr['wick_ratio_short']
        rsi_ext = (os_th - rsi) / max(os_th, 1e-9) if direction == "long" \
            else (rsi - ob_th) / max(100.0 - ob_th, 1e-9)
        strength = int(max(80, min(100, 80 + (wick_val - 0.7)*100 + rsi_ext * 20 + booster_bonus)))

        tag_str = booster_m.get("booster_tag", "")
        reason = (f"{booster_reason} | 꼬리 사냥 성공 (Wick: {wick_val:.2f}) + RSI {rsi:.1f} "
                  f"→ RR {rr_ratio:.2f}:1 (TP {tp_pct*100:.2f}% / SL {sl_pct*100:.2f}%)")

        logger.info(f"[WickHunter] {symbol} {direction.upper()} | 종가 {c:.6g} "
                    f"| Wick {wick_val:.2f} | RSI {rsi:.1f} "
                    f"| TP {tp_price:.6g}({tp_pct*100:.2f}%) SL {sl_price:.6g}({sl_pct*100:.2f}%)")"""

if old_1 in content: content = content.replace(old_1, new_1)
else: print("old_1 not found!")

if old_2 in content: content = content.replace(old_2, new_2)
else: print("old_2 not found!")

if old_3 in content: content = content.replace(old_3, new_3)
else: print("old_3 not found!")

with open(filepath, "w") as f:
    f.write(content)
print("Patched successfully.")
