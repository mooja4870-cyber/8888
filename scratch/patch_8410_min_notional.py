#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8410 봇 (Binance 선물) 최소 주문금액(Notional >= 5 USDT) 미달 방어 및 마진 하한선 패치 스크립트
"""
import os
import sys
import json
import shutil
from datetime import datetime

BOT_DIR = "/Users/l/project/8410"

def patch_trader_py():
    trader_path = os.path.join(BOT_DIR, "core", "trader.py")
    with open(trader_path, "r", encoding="utf-8") as f:
        code = f.read()

    # 1) 기본 마진 / 복리 마진 하한선
    target_base = """            else:
                margin_usdt = self.cfg.MARGIN_USDT * getattr(self.cfg, 'EQUITY_SCALE_FACTOR', 1.0)
                logger.info(f"[MARGIN] 고정 모드: ${margin_usdt:.2f}")

            logger.info(
                f"[MARGIN DECISION] symbol={sig.symbol} source={margin_source} """

    replacement_base = """            else:
                margin_usdt = self.cfg.MARGIN_USDT * getattr(self.cfg, 'EQUITY_SCALE_FACTOR', 1.0)
                logger.info(f"[MARGIN] 고정 모드: ${margin_usdt:.2f}")

            # [바이낸스 최소 Notional 5.0 USDT 보장 기본 마진 하한선]
            if str(getattr(self.cfg, "EXCHANGE_ID", "")).lower() == "binance":
                _min_m = round(5.2 / float(self.cfg.LEVERAGE), 2)
                if margin_usdt < _min_m:
                    logger.info(f"[MARGIN FLOOR] 바이낸스 최소 명목가(5.0 USDT) 보장을 위해 마진 하한선 적용: ${margin_usdt:.2f} → ${_min_m:.2f}")
                    margin_usdt = _min_m

            logger.info(
                f"[MARGIN DECISION] symbol={sig.symbol} source={margin_source} """

    if target_base in code:
        code = code.replace(target_base, replacement_base)
        print("✅ [trader.py] 기본/복리 마진 바이낸스 Notional 하한선 적용")
    elif "[MARGIN FLOOR]" in code:
        print("ℹ️ [trader.py] 기본/복리 마진 하한선 이미 적용됨")
    else:
        print("⚠️ [trader.py] target_base 매칭 실패, 확인 필요")

    # 2) M4 SIZING 하한선
    target_m4 = """                        # 30% 캡 방어
                        margin_cap = total_bal * 0.30
                        calc_margin_usdt = min(calc_margin_usdt, margin_cap)
                        
                        calc_margin_usdt = max(1.0, calc_margin_usdt)
                        
                        margin_usdt = round(calc_margin_usdt, 2)
                        margin_source = "risk_based_m4"
                        logger.info(
                            f"[M4 SIZING] {sig.symbol} 잔고=${total_bal:.2f}, "
                            f"리스크={risk_pct*100:.2f}%, SL거리={sl_pct*100:.2f}% "
                            f"→ 증거금=${margin_usdt:.2f} (Notional: ${margin_usdt*lev:.2f})"
                        )"""

    replacement_m4 = """                        # 30% 캡 방어
                        margin_cap = total_bal * 0.30
                        calc_margin_usdt = min(calc_margin_usdt, margin_cap)
                        
                        # [바이낸스 최소 Notional 5.0 USDT 보장 하한선]
                        is_binance = str(getattr(self.cfg, "EXCHANGE_ID", "")).lower() == "binance"
                        min_notional_margin = round(5.2 / lev, 2) if is_binance else 1.0
                        calc_margin_usdt = max(min_notional_margin, calc_margin_usdt)
                        
                        margin_usdt = round(calc_margin_usdt, 2)
                        margin_source = "risk_based_m4"
                        logger.info(
                            f"[M4 SIZING] {sig.symbol} 잔고=${total_bal:.2f}, "
                            f"리스크={risk_pct*100:.2f}%, SL거리={sl_pct*100:.2f}% "
                            f"→ 증거금=${margin_usdt:.2f} (Notional: ${margin_usdt*lev:.2f})"
                        )"""

    if target_m4 in code:
        code = code.replace(target_m4, replacement_m4)
        print("✅ [trader.py] M4 SIZING 바이낸스 Notional 하한선 적용")
    elif "min_notional_margin = round(5.2 / lev, 2)" in code:
        print("ℹ️ [trader.py] M4 SIZING 하한선 이미 적용됨")
    else:
        print("⚠️ [trader.py] target_m4 매칭 실패, 확인 필요")

    with open(trader_path, "w", encoding="utf-8") as f:
        f.write(code)

def patch_exchange_py():
    exchange_path = os.path.join(BOT_DIR, "core", "exchange.py")
    with open(exchange_path, "r", encoding="utf-8") as f:
        code = f.read()

    target_amt = """            amount = (margin_usdt * applied_leverage) / price
            amount = float(self.exchange.amount_to_precision(symbol, amount))

            market = self._markets.get(symbol, {})
            min_amount = market.get('limits', {}).get('amount', {}).get('min', 0.0)"""

    replacement_amt = """            amount = (margin_usdt * applied_leverage) / price
            amount = float(self.exchange.amount_to_precision(symbol, amount))

            market = self._markets.get(symbol, {})
            # [바이낸스 최소 주문 명목가치(Notional >= 5.0 USDT) 미달 방어 및 자동 보정]
            min_cost = market.get('limits', {}).get('cost', {}).get('min', 0.0) or 0.0
            if not min_cost and str(getattr(CFG, "EXCHANGE_ID", "")).lower() == "binance":
                min_cost = 5.0

            if min_cost > 0 and (amount * price) < min_cost:
                safe_min_notional = min_cost * 1.02
                adjusted_amount = float(self.exchange.amount_to_precision(symbol, safe_min_notional / price))
                req_margin = round((adjusted_amount * price) / applied_leverage, 2)
                try:
                    bal = await self.get_balance()
                    free_usdt = float(bal.get("free", 0.0) or 0.0)
                    total_bal = float(bal.get("total", 0.0) or 0.0)
                except Exception:
                    free_usdt = total_bal = margin_usdt * 2.0
                if req_margin <= total_bal * 0.35 and req_margin <= free_usdt:
                    logger.info(
                        f"[{symbol}] 주문 명목가치 자동 보정: ${amount * price:.2f} < ${min_cost:.2f} "
                        f"→ 수량 {amount}→{adjusted_amount} (명목가 ${adjusted_amount * price:.2f}, 증거금 ${req_margin:.2f})"
                    )
                    amount = adjusted_amount
                    margin_usdt = req_margin
                else:
                    logger.warning(
                        f"[{symbol}] 주문 명목가치(${amount * price:.2f})가 거래소 최소 기준(${min_cost:.2f}) 미만이나, "
                        f"필요 증거금(${req_margin:.2f})이 잔고 한도 초과로 주문을 생략합니다."
                    )
                    return None

            min_amount = market.get('limits', {}).get('amount', {}).get('min', 0.0)"""

    if target_amt in code:
        code = code.replace(target_amt, replacement_amt)
        print("✅ [exchange.py] place_order 최소 Notional 자동 보정 적용")
    elif "주문 명목가치 자동 보정" in code:
        print("ℹ️ [exchange.py] place_order 최소 Notional 자동 보정 이미 적용됨")
    else:
        print("⚠️ [exchange.py] target_amt 매칭 실패, 확인 필요")

    with open(exchange_path, "w", encoding="utf-8") as f:
        f.write(code)

def patch_config_json():
    cfg_path = os.path.join(BOT_DIR, "config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg["MARGIN_USDT"] = 2.0
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)
    print("✅ [config.json] MARGIN_USDT 1.5 → 2.0 상향 완료")

if __name__ == "__main__":
    patch_trader_py()
    patch_exchange_py()
    patch_config_json()
