#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8407 & 8409 손익비 개선 패치 스크립트:
1. MIN_ENTRY_RR (1:1.0) 게이트 및 USE_RISK_NORMALIZED_SIZING 장착
2. 8409 SL 상/하한선 정상화 (MAX_SL 0.05, MIN_SL 0.01)
3. 타임스탑 기준 정비 (TIMEOUT_SKIP_PROFITABLE 가드 및 OCO 완주 정비)
"""
import os
import json
import re

BOTS = [8407, 8409]

RR_GATE_CODE = """            # ── [Tier A ②] 손익비 하한 게이트 (8401 이식) ──
            _min_rr = float(getattr(self.cfg, "MIN_ENTRY_RR", 0.0) or 0.0)
            if _min_rr > 0 and dynamic_sl_pct > 0:
                _rr_now = dynamic_tp_pct / dynamic_sl_pct
                if _rr_now < _min_rr:
                    _reason = (f"손익비 미달 RR 1:{_rr_now:.2f} < 1:{_min_rr:.2f} "
                               f"(SL {dynamic_sl_pct*100:.2f}% / TP {dynamic_tp_pct*100:.2f}%)")
                    logger.info(f"[RR GATE] {sig.symbol} — {_reason}")
                    self.pending_entry_locks.pop(sig.symbol, None)
                    self._log_trade(sig, status="BLOCKED", reason=_reason)
                    return

            # ── [Tier A ①] 리스크 균등화 사이징 (8401 이식) ──
            if bool(getattr(self.cfg, "USE_RISK_NORMALIZED_SIZING", False)) and dynamic_sl_pct > 0:
                _ref = float(getattr(self.cfg, "RISK_NORM_REF_SL_PCT", 0.02))
                _lo = float(getattr(self.cfg, "RISK_NORM_MIN_MULT", 0.8))
                _hi = float(getattr(self.cfg, "RISK_NORM_MAX_MULT", 1.5))
                _mult = max(_lo, min(_hi, _ref / dynamic_sl_pct))
                _before = margin_usdt
                margin_usdt = round(margin_usdt * _mult, 2)
                margin_source = f"{margin_source}+risknorm"
                logger.info(
                    f"[RISK NORM] {sig.symbol} SL {dynamic_sl_pct*100:.2f}% "
                    f"(기준 {_ref*100:.2f}%) → 증거금 배수 {_mult:.2f} "
                    f": ${_before:.2f} → ${margin_usdt:.2f}"
                )
                _min_margin = float(getattr(self.cfg, "MIN_MARGIN_USDT", 1.0))
                if margin_usdt < _min_margin:
                    _reason = (f"정규화 후 증거금 ${margin_usdt:.2f} < 최소 ${_min_margin:.2f} "
                               f"(SL {dynamic_sl_pct*100:.2f}%)")
                    logger.info(f"[RISK NORM] {sig.symbol} 진입 포기 — {_reason}")
                    self.pending_entry_locks.pop(sig.symbol, None)
                    self._log_trade(sig, status="BLOCKED", reason=_reason)
                    return
"""

CONFIG_PY_VARS = """    # ── [Tier A] 손익비 게이트 & 리스크 균등화 사이징 (8401 이식) ──
    MIN_ENTRY_RR: float = 1.0              # 최소 진입 손익비 (RR < 1.0 거래 원천 차단)
    USE_RISK_NORMALIZED_SIZING: bool = True # 손절폭 반비례 증거금 정규화
    RISK_NORM_REF_SL_PCT: float = 0.02    # 기준 손절폭 (2%)
    RISK_NORM_MIN_MULT: float = 0.8       # 넓은 손절 → 증거금 축소 하한
    RISK_NORM_MAX_MULT: float = 1.5       # 좁은 손절 → 증거금 확대 상한
    MIN_MARGIN_USDT: float = 1.0          # 정규화 후 최소 증거금
"""

def patch_trader_py(bot_id):
    path = f"/Users/l/project/{bot_id}/core/trader.py"
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()

    if "[RR GATE]" in code:
        print(f"[{bot_id}] trader.py 이미 RR GATE 적용됨")
        return

    # [SL CAP] 블록 뒤, [FINAL ENTRY] 로깅 직전 삽입
    target = '            # 🔴 최종 진입 로깅\n            logger.info('
    if target not in code:
        raise ValueError(f"[{bot_id}] trader.py 타겟 위치 미발견")

    new_code = code.replace(target, RR_GATE_CODE + "\n" + target)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_code)
    print(f"✅ [{bot_id}] trader.py MIN_ENTRY_RR 및 리스크 정규화 사이징 장착 완료")


def patch_config_py(bot_id):
    path = f"/Users/l/project/{bot_id}/core/config.py"
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()

    if "MIN_ENTRY_RR" in code:
        print(f"[{bot_id}] config.py 이미 MIN_ENTRY_RR 존재")
        return

    # USE_BE_GUARD 바로 위에 선언 추가
    target = '    USE_BE_GUARD: bool = False'
    if target not in code:
        raise ValueError(f"[{bot_id}] config.py USE_BE_GUARD 미발견")

    new_code = code.replace(target, CONFIG_PY_VARS + "\n" + target)

    if bot_id == 8409:
        # 8409 SL 상/하한 기본값 정상화
        new_code = re.sub(r'MAX_SL_PCT:\s*float\s*=\s*0\.015', 'MAX_SL_PCT: float = 0.05', new_code)
        new_code = re.sub(r'MIN_SL_PCT:\s*float\s*=\s*0\.025', 'MIN_SL_PCT: float = 0.01', new_code)

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_code)
    print(f"✅ [{bot_id}] config.py 필드 선언 및 SL 상하한 정상화 완료")


def patch_trailing_stop_manager(bot_id):
    path = f"/Users/l/project/{bot_id}/core/trailing_stop_manager.py"
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()

    if "[TIME STOP SKIP]" in code:
        print(f"[{bot_id}] trailing_stop_manager.py 이미 TIME STOP SKIP 적용됨")
        return

    target = '                    move = (mark_price - entry_price) if side == "long" else (entry_price - mark_price)\n                    if move < atr * min_progress:'
    replacement = '''                    move = (mark_price - entry_price) if side == "long" else (entry_price - mark_price)
                    
                    # [타임스탑 기준 정비] 수익 중인 포지션은 조기 절단하지 않고 승자 유예 (OCO TP 완주 보장)
                    if bool(getattr(self.engine.cfg, "TIMEOUT_SKIP_PROFITABLE", True)) and move > 0:
                        logger.info(f"[TIME STOP SKIP] {sym} {side} - 진입 후 {max_candles}캔들 경과했으나 수익 중(+{move:.4f})이므로 청산 유예")
                        continue

                    if move < atr * min_progress:'''

    if target not in code:
        # 줄바꿈 차이 등 대응
        target_alt = 'move = (mark_price - entry_price) if side == "long" else (entry_price - mark_price)'
        if target_alt in code:
            code = code.replace(target_alt, target_alt + '\n                    if bool(getattr(self.engine.cfg, "TIMEOUT_SKIP_PROFITABLE", True)) and move > 0:\n                        continue')
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            print(f"✅ [{bot_id}] trailing_stop_manager.py 타임스탑 수익 유예 가드 적용 (대체 경로)")
            return
        raise ValueError(f"[{bot_id}] trailing_stop_manager.py 타임스탑 타겟 미발견")

    new_code = code.replace(target, replacement)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_code)
    print(f"✅ [{bot_id}] trailing_stop_manager.py 타임스탑 수익 유예 가드 적용 완료")


def patch_config_json(bot_id):
    path = f"/Users/l/project/{bot_id}/config.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["MIN_ENTRY_RR"] = 1.0
    data["USE_RISK_NORMALIZED_SIZING"] = True
    data["RISK_NORM_REF_SL_PCT"] = 0.02
    data["RISK_NORM_MIN_MULT"] = 0.8
    data["RISK_NORM_MAX_MULT"] = 1.5
    data["MIN_MARGIN_USDT"] = 1.0

    # 타임스탑 기준 정비: 어정쩡한 중간 청산 끄고 오더북 SL/TP 완주 보장 (8401과 동일화)
    data["USE_TIME_STOP"] = False
    data["TIMEOUT_SKIP_PROFITABLE"] = True
    data["MAX_HOLDING_HOURS"] = 168.0

    if bot_id == 8409:
        data["MAX_SL_PCT"] = 0.05
        data["MIN_SL_PCT"] = 0.01
        data["DYNAMIC_SL_CAP_PCT"] = 0.05
        print("  - 8409 SL 상/하한 정상화: MAX_SL=0.05, MIN_SL=0.01")
    elif bot_id == 8407:
        data["MAX_SL_PCT"] = 0.05
        data["MIN_SL_PCT"] = 0.01
        data["DYNAMIC_SL_CAP_PCT"] = 0.05

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"✅ [{bot_id}] config.json 파라미터 갱신 완료")


def update_ver_md(bot_id):
    path = f"/Users/l/project/{bot_id}/ver.md"
    with open(path, "r", encoding="utf-8") as f:
        old_content = f.read()

    new_section = """## v11.5.0

Date: 2026-09-05

### 변경 내용
* [손익비 게이트 장착] MIN_ENTRY_RR=1.0 도입으로 기대 손익비 1:1 미달 거래 원천 차단 (8401 우수 로직 이식)
* [리스크 균등화 사이징] USE_RISK_NORMALIZED_SIZING 활성화 (손절폭 역비례 증거금 조절로 USDT 손실 일정화)
* [타임스탑 기준 정비] USE_TIME_STOP=False 전환 및 수익 중 포지션 유예 가드 추가 (8401형 오더북 OCO SL/TP 완주 체제)
* [8409 손절 상하한 정상화] MAX_SL_PCT 5.0%, MIN_SL_PCT 1.0%로 상하한 역전 모순 전면 해소

### 수정 파일
* config.json
* core/config.py
* core/trader.py
* core/trailing_stop_manager.py
* ver.md

### 비고
* 8401 수준의 정돈되고 일관된 손익비 구조 체계 확립

"""
    # Version History 바로 뒤에 삽입
    target = '# Version History\n\n'
    if target in old_content:
        updated = old_content.replace(target, target + new_section)
    else:
        updated = '# Version History\n\n' + new_section + old_content

    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)
    print(f"✅ [{bot_id}] ver.md v11.5.0 갱신 완료")


if __name__ == "__main__":
    for b in BOTS:
        print(f"\n==================== [봇 {b} 패치 시작] ====================")
        patch_config_py(b)
        patch_trader_py(b)
        patch_trailing_stop_manager(b)
        patch_config_json(b)
        update_ver_md(b)
    print("\n🎉 모든 봇 패치 완료!")
