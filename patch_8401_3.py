import re

filepath = "/Users/l/project/8401/core/strategy.py"
with open(filepath, "r") as f:
    content = f.read()

old_3 = r'''        # \[부스터 4: 비대칭 동적 손익비\] ATR 기반 동적 손절 산출 \(1\.2% ~ 2\.5%\)
        atr_sl_mult = float\(getattr\(self\.cfg, 'BOOSTER_ATR_SL_MULT', 1\.5\)\)
        min_sl = float\(getattr\(self\.cfg, 'BOOSTER_MIN_SL_PCT', 0\.012\)\)
        max_sl = float\(getattr\(self\.cfg, 'BOOSTER_MAX_SL_PCT', 0\.025\)\)
        sl_dist = min\(c \* max_sl, max\(c \* min_sl, atr_sl_mult \* atr\)\) if atr > 0 else \(c \* 0\.015\)
        
        if direction == "long":
            sl_price = c - sl_dist
        else:
            sl_price = c \+ sl_dist
        sl_pct = sl_dist / c
        rr_ratio = tp_pct / max\(sl_pct, 1e-9\)

        # \[부스터 5: 50% 분할익절 목표가 설정\] 중앙선 거리 60% 지점
        tp1_price = c \+ \(mid - c\) \* 0\.6

        # 강도: 밴드 이탈 정도 \+ RSI 극단 \+ 부스터 가산 보너스 \(최대 100\)
        band_w = max\(up - dn, 1e-12\)
        excess = \(dn - c\) / band_w if direction == "long" else \(c - up\) / band_w
        rsi_ext = \(os_th - rsi\) / max\(os_th, 1e-9\) if direction == "long" \\
            else \(rsi - ob_th\) / max\(100\.0 - ob_th, 1e-9\)
        strength = int\(max\(80, min\(100, 80 \+ excess \* 100 \+ rsi_ext \* 20 \+ booster_bonus\)\)\)

        tag_str = booster_m\.get\("booster_tag", ""\)
        reason = \(f"\{booster_reason\} \| 볼린저 \{'하단' if direction == 'long' else '상단'\} 이탈 "
                  f"\(종가 \{c:\.6g\} / 밴드 \{dn:\.6g\}~\{up:\.6g\}\) \+ RSI \{rsi:\.1f\} "
                  f"→ RR \{rr_ratio:\.2f\}:1 \(TP \{tp_pct\*100:\.2f\}% / SL \{sl_pct\*100:\.2f\}%\)"\)

        logger\.info\(f"\[BB-MR\] \{symbol\} \{direction\.upper\(\)\} \| 종가 \{c:\.6g\} "
                    f"\| 밴드 \{dn:\.6g\}~\{up:\.6g\} \| RSI \{rsi:\.1f\} "
                    f"\| TP \{mid:\.6g\}\(\{tp_pct\*100:\.2f\}%\) SL \{sl_price:\.6g\}\(\{sl_pct\*100:\.2f\}%\)"\)'''

new_3 = r'''        # [부스터 오버라이드] 백테스트 골든 파라미터 강제 주입
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
                    f"| TP {tp_price:.6g}({tp_pct*100:.2f}%) SL {sl_price:.6g}({sl_pct*100:.2f}%)")'''

content = re.sub(old_3, new_3, content, flags=re.DOTALL)
with open(filepath, "w") as f:
    f.write(content)
print("Regex patch applied.")
