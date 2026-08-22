#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8402 봇 세력흔적 전략 숏(Short) 포지션 진입 기능 추가 패치 스크립트
"""
import json
import os
import sys

BOT_DIR = "/Users/l/project/8402"

def patch_config_json():
    cfg_path = os.path.join(BOT_DIR, "config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["ALLOW_SHORT"] = True
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("✅ config.json ALLOW_SHORT=True 반영 완료")

def patch_core_config():
    cfg_path = os.path.join(BOT_DIR, "core", "config.py")
    with open(cfg_path, "r", encoding="utf-8") as f:
        content = f.read()
    if "ALLOW_SHORT: bool = False" in content:
        content = content.replace("ALLOW_SHORT: bool = False", "ALLOW_SHORT: bool = True")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("✅ core/config.py ALLOW_SHORT=True 반영 완료")
    else:
        print("ℹ️ core/config.py ALLOW_SHORT 상태 유지")

def patch_strategy():
    strat_path = os.path.join(BOT_DIR, "core", "strategy.py")
    with open(strat_path, "r", encoding="utf-8") as f:
        code = f.read()

    old_func_start = "def _generate_signal_sniper(self, df, symbol):"
    
    new_func = '''def _generate_signal_sniper(self, df, symbol):
    nb = int(getattr(self.cfg, "SNIPER_N_BREAK", SNIPER_N_BREAK))
    nv = int(getattr(self.cfg, "SNIPER_N_VOL", SNIPER_N_VOL))
    m_fast = float(getattr(self.cfg, "SNIPER_M_FAST", SNIPER_M_FAST))
    m_slow = float(getattr(self.cfg, "SNIPER_M_SLOW", SNIPER_M_SLOW))
    tp1 = float(getattr(self.cfg, "SNIPER_TP1_PCT", SNIPER_TP1_PCT))
    allow_l = bool(getattr(self.cfg, "ALLOW_LONG", True))
    allow_s = bool(getattr(self.cfg, "ALLOW_SHORT", True))

    def _no(reason):
        return Signal(symbol=symbol, direction="none", strength=0,
                      ema_ok=False, bb_ok=False, macd_ok=False,
                      close=0.0, ema200=0.0, bb_upper=0.0, bb_lower=0.0,
                      macd_hist=0.0, reason=reason,
                      regime="Trend", strategy_type="Sniper15")

    if not allow_l and not allow_s:
        return _no("롱/숏 모두 차단 설정 (관망)")
    need = nb + nv + 60
    if df is None or df.empty or len(df) < need:
        return _no("데이터 부족 (관망)")

    # 미완성 현재봉 제외 — 문서 원칙1의 '종가 완성 필수'
    d = df.iloc[:-1]
    if len(d) < need - 1:
        return _no("데이터 부족 (관망)")

    c = d["close"].values
    o = d["open"].values
    h = d["high"].values
    l = d["low"].values
    v = d["volume"].values

    cs = pd.Series(c)
    hi_c = cs.rolling(nb).max().shift(1).values          # Highest(C,15) — 직전까지
    hi_c_p = cs.rolling(nb).max().shift(2).values        # Highest(C,15,1)
    lo_c = cs.rolling(nb).min().shift(1).values          # Lowest(C,15) — 직전까지
    lo_c_p = cs.rolling(nb).min().shift(2).values        # Lowest(C,15,1)
    hi_h = pd.Series(h).rolling(nb).max().shift(1).values
    lo_l = pd.Series(l).rolling(nb).min().shift(1).values
    vema = pd.Series(v).ewm(span=nv, adjust=False).mean().values
    if not (np.isfinite(hi_c[-1]) and np.isfinite(hi_c_p[-1]) and
            np.isfinite(lo_c[-1]) and np.isfinite(lo_c_p[-1]) and
            np.isfinite(vema[-1])):
        return _no("지표 미확정 (관망)")

    px = float(c[-1])
    if px <= 0:
        return _no("가격 이상 (관망)")

    # ── 세력라인·마지노선 계산 ──
    atr = _sniper_atr(d, int(getattr(self.cfg, "SNIPER_ATR_LEN", SNIPER_ATR_LEN)))
    fast = _sniper_line(d, m_fast, atr)
    slow = _sniper_line(d, m_slow, atr)
    if not (np.isfinite(fast[-1]) and np.isfinite(slow[-1])):
        return _no("라인 미확정 (관망)")

    min_sl = float(getattr(self.cfg, "MIN_SL_PCT", 0.005))
    max_sl = float(getattr(self.cfg, "MAX_SL_PCT", 0.15))
    atr_now = float(atr[-1]) if np.isfinite(atr[-1]) else 0.0

    # ── 1) 롱(Long) 신호 판정 ──
    if allow_l:
        x1 = c[-1] > hi_c[-1]
        x2 = c[-2] < hi_c_p[-1]
        x3 = c[-1] > o[-1]
        x4 = v[-1] > vema[-1]
        x5 = c[-1] > (hi_h[-1] + lo_l[-1]) / 2.0
        line_break_l = (px > fast[-1] and px > slow[-1])

        if x1 and x2 and x3 and x4 and x5 and line_break_l:
            sl_price = float(slow[-1])
            risk = (px - sl_price) / px
            if risk < min_sl:
                sl_price = px * (1 - min_sl)
                risk = min_sl
            if risk <= max_sl:
                tp_price = px * (1 + tp1)
                gap = (px - slow[-1]) / px * 100.0
                strength = int(max(50, min(95, 55 + gap * 8)))
                return Signal(
                    symbol=symbol, direction="long", strength=strength,
                    ema_ok=True, bb_ok=True, macd_ok=True,
                    close=px, ema200=float(slow[-1]),
                    bb_upper=float(fast[-1]), bb_lower=float(slow[-1]),
                    macd_hist=float(v[-1] / vema[-1]) if vema[-1] > 0 else 0.0,
                    reason=(f"[세력흔적 LONG] 신호수식 5조건 + 세력라인({fast[-1]:.6g})·"
                            f"마지노선({slow[-1]:.6g}) 종가돌파 | 손절 −{risk*100:.2f}% "
                            f"| 1차익절 +{tp1*100:.0f}%"),
                    rsi=50.0, rsi_ok=True, ema200_ok=True,
                    atr=atr_now, adx=0.0, regime="Trend", strategy_type="Sniper15",
                    bb_mid=tp_price, vol_ok=True,
                    swing_sl_price=sl_price, tp1_price=tp_price, entry_price=px,
                )

    # ── 2) 숏(Short) 신호 판정 ──
    if allow_s:
        s1 = c[-1] < lo_c[-1]
        s2 = c[-2] > lo_c_p[-1]
        s3 = c[-1] < o[-1]
        s4 = v[-1] > vema[-1]
        s5 = c[-1] < (hi_h[-1] + lo_l[-1]) / 2.0
        line_break_s = (px < fast[-1] and px < slow[-1])

        if s1 and s2 and s3 and s4 and s5 and line_break_s:
            sl_price = float(slow[-1])
            risk = (sl_price - px) / px
            if risk < min_sl:
                sl_price = px * (1 + min_sl)
                risk = min_sl
            if risk <= max_sl:
                tp_price = px * (1 - tp1)
                gap = (slow[-1] - px) / px * 100.0
                strength = int(max(50, min(95, 55 + gap * 8)))
                return Signal(
                    symbol=symbol, direction="short", strength=strength,
                    ema_ok=True, bb_ok=True, macd_ok=True,
                    close=px, ema200=float(slow[-1]),
                    bb_upper=float(fast[-1]), bb_lower=float(slow[-1]),
                    macd_hist=float(v[-1] / vema[-1]) if vema[-1] > 0 else 0.0,
                    reason=(f"[세력흔적 SHORT] 신호수식 5조건 + 세력라인({fast[-1]:.6g})·"
                            f"마지노선({slow[-1]:.6g}) 종가이탈 | 손절 −{risk*100:.2f}% "
                            f"| 1차익절 +{tp1*100:.0f}%"),
                    rsi=50.0, rsi_ok=True, ema200_ok=True,
                    atr=atr_now, adx=0.0, regime="Trend", strategy_type="Sniper15",
                    bb_mid=tp_price, vol_ok=True,
                    swing_sl_price=sl_price, tp1_price=tp_price, entry_price=px,
                )

    return _no("신호 조건 미충족 (관망)")
'''
    
    idx = code.find(old_func_start)
    if idx == -1:
        print("❌ _generate_signal_sniper 함수를 찾을 수 없습니다.")
        return False

    # StrategyEngine.generate_signal = _generate_signal_sniper 이전까지 교체
    tail_marker = "StrategyEngine.generate_signal = _generate_signal_sniper"
    tail_idx = code.find(tail_marker)
    if tail_idx == -1:
        print("❌ tail_marker를 찾을 수 없습니다.")
        return False

    new_code = code[:idx] + new_func + "\n\n" + code[tail_idx:]
    with open(strat_path, "w", encoding="utf-8") as f:
        f.write(new_code)
    print("✅ core/strategy.py 숏 신호 로직 패치 완료")
    return True

if __name__ == "__main__":
    patch_config_json()
    patch_core_config()
    patch_strategy()
