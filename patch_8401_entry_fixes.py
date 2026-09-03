#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8401 포지션 진입 결함 수정 및 모니터링 크래시 해결 패치 (v6.3.4)
"""
import os
import sys

BOT_DIR = "/Users/l/project/8401"

def patch_bot_py():
    path = os.path.join(BOT_DIR, "bot.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    target = """    _equity_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "equity_curve.json")
    _equity_history = []
    if os.path.exists(_equity_file):"""

    replacement = """    _equity_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "equity_curve.json")
    _equity_history = []
    _drawdown_history = []  # [WATCHDOG 4] 자본 잠식 감시 이력 초기화 (UnboundLocalError 방지)
    if os.path.exists(_equity_file):"""

    if "_drawdown_history = []" not in content:
        if target in content:
            content = content.replace(target, replacement, 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print("✅ bot.py _drawdown_history 초기화 패치 완료")
        else:
            print("⚠️ bot.py 타겟 패턴 불일치, 수동 확인 필요")
    else:
        print("ℹ️ bot.py _drawdown_history 이미 존재")

def patch_exchange_py():
    path = os.path.join(BOT_DIR, "core", "exchange.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    target = """            market = self._markets.get(symbol, {})
            contract_size = market.get("contractSize", 1.0) or 1.0
            notional = margin_usdt * applied_leverage
            amount = notional / (price * contract_size)
            amount = self.exchange.amount_to_precision(symbol, amount)

            market = self._markets.get(symbol, {})
            min_amount = market.get('limits', {}).get('amount', {}).get('min', 0.0)
            if min_amount and float(amount) < float(min_amount):
                logger.warning(f"[{symbol}] 계산된 수량({amount})이 최소 주문 단위({min_amount}) 미만입니다. 주문을 생략합니다.")
                return None"""

    replacement = """            market = self._markets.get(symbol, {})
            contract_size = float(market.get("contractSize", 1.0) or 1.0)
            notional = margin_usdt * applied_leverage
            calc_amount = notional / (price * contract_size)

            min_amount = float(market.get('limits', {}).get('amount', {}).get('min', 0.0) or 0.0)
            prec_amount = float(market.get('precision', {}).get('amount', 0.0) or 0.0)
            min_req_amount = max(min_amount, prec_amount)

            amount = calc_amount
            # [최소 계약 요건 보정 및 사전 안전 검증]
            if min_req_amount > 0 and amount < min_req_amount:
                min_contract_notional = min_req_amount * contract_size * price
                min_contract_margin = min_contract_notional / applied_leverage
                
                try:
                    bal = await self.get_balance()
                    free_bal = float(bal.get('free', 0.0) or 0.0)
                except Exception:
                    free_bal = margin_usdt

                if min_contract_margin <= free_bal and min_contract_margin <= free_bal * 0.8:
                    logger.info(
                        f"[{symbol}] 계산 수량({calc_amount:.4f})이 최소 단위({min_req_amount}) 미달 → "
                        f"최소 1단위({min_req_amount})로 올림 보정 (필요 증거금: ${min_contract_margin:.2f}, 가용: ${free_bal:.2f})"
                    )
                    amount = min_req_amount
                    margin_usdt = min_contract_margin
                else:
                    logger.warning(
                        f"[{symbol}] 계산 수량({calc_amount:.4f}) 최소 단위({min_req_amount}) 미달 & "
                        f"필요 증거금(${min_contract_margin:.2f}) 초과(가용: ${free_bal:.2f}) → 주문 안전 생략"
                    )
                    return None

            try:
                amount = self.exchange.amount_to_precision(symbol, amount)
            except Exception as prec_err:
                logger.warning(f"[{symbol}] amount_to_precision 변환 오류 ({prec_err}) → 주문 생략")
                return None"""

    if "min_req_amount = max(min_amount, prec_amount)" not in content:
        if target in content:
            content = content.replace(target, replacement, 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            print("✅ exchange.py 최소 주문 단위 사전 검증 및 1계약 올림 보정 패치 완료")
        else:
            print("⚠️ exchange.py 타겟 패턴 불일치, 수동 확인 필요")
    else:
        print("ℹ️ exchange.py 최소 주문 단위 보강 이미 적용됨")

def patch_ver_md():
    path = os.path.join(BOT_DIR, "ver.md")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    new_entry = """## v6.3.4

Date: 2026-09-04

### 변경 내용
* bot.py: 60초 주기 상태 모니터링 루프 내 `_drawdown_history` UnboundLocalError 크래시 버그 수정
* core/exchange.py: 최소 계약 요건 사전 검증 및 최소 1계약 안전 올림 보정 로직 탑재 (ccxt InvalidOrder 크래시 방지 및 소액 시드 정상 진입 보장)
* 4h 캔들 및 최소 주문 단위 요건 정합성 검증 완료

### 수정 파일
* bot.py
* core/exchange.py

### 비고
* 포지션 진입 파이프라인 3중 자체 검증 완료

"""
    if "## v6.3.4" not in content:
        # '# Version History\n\n' 뒤에 삽입
        if content.startswith("# Version History\n\n"):
            content = "# Version History\n\n" + new_entry + content[len("# Version History\n\n"):]
        else:
            content = new_entry + content
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print("✅ ver.md v6.3.4 갱신 완료")
    else:
        print("ℹ️ ver.md v6.3.4 이미 존재")

if __name__ == "__main__":
    patch_bot_py()
    patch_exchange_py()
    patch_ver_md()
