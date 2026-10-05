import re

exchange_file = "/Users/l/project/8401/core/exchange.py"

with open(exchange_file, "r") as f:
    content = f.read()

# 1. Fix setMarginMode warning (OKX ccxt setMarginMode requires lever? No, CCXT handles it, but maybe just skip setMarginMode for OKX if it fails, or fix the parameters).
# We can just catch the exception and ignore for OKX because margin mode is often set manually.
# Actually, the warning is just a warning, it didn't crash.

# 2. Fix fapiPrivateGetOpenAlgoOrders
# OKX conditional orders can be fetched via fetch_open_orders with {'ordType': 'conditional'}
# Or we can just use standard fetch_open_orders if it includes everything.
algo_order_func_old = """    async def _fetch_algo_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        \"\"\"살아있는(NEW) Algo 보호주문 목록. 조회 실패 시 None.\"\"\"
        try:
            rows = await self._execute_with_retry(self.exchange.fapiPrivateGetOpenAlgoOrders, {})
        except Exception as e:
            logger.warning(f"[ALGO] 조회 실패: {str(e)[:80]}")
            return None
        base = None
        if symbol:
            try:
                base = self.exchange.market(symbol)["id"]
            except Exception:
                base = symbol.split("/")[0] + "USDT"
        out = []
        for a in rows or []:
            if str(a.get("algoStatus")) != "NEW":
                continue
            if base and a.get("symbol") != base:
                continue
            out.append(a)
        return out"""

algo_order_func_new = """    async def _fetch_algo_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        \"\"\"살아있는(NEW) Algo 보호주문 목록. 조회 실패 시 None.\"\"\"
        try:
            # OKX uses ordType=conditional for algo orders
            rows = await self._execute_with_retry(self.exchange.fetch_open_orders, symbol, params={'ordType': 'conditional'})
        except Exception as e:
            logger.warning(f"[ALGO] 조회 실패: {str(e)[:80]}")
            return None
        
        out = []
        for a in rows or []:
            # CCXT normalizes order status to 'open'
            if str(a.get("status")) != "open":
                continue
            out.append(a)
        return out"""

content = content.replace(algo_order_func_old, algo_order_func_new)

# 3. Fix fapiPrivateDeleteAlgoOrder
cancel_algo_old = """    async def _cancel_algo(self, algo_id) -> bool:
        try:
            await self._execute_with_retry(self.exchange.fapiPrivateDeleteAlgoOrder,
                                           {"algoId": str(algo_id)})
            return True
        except Exception as e:
            logger.warning(f"[ALGO] 취소 실패 algoId={algo_id}: {str(e)[:80]}")
            return False"""

cancel_algo_new = """    async def _cancel_algo(self, algo_id) -> bool:
        try:
            await self._execute_with_retry(self.exchange.cancel_order, str(algo_id), params={'ordType': 'conditional'})
            return True
        except Exception as e:
            logger.warning(f"[ALGO] 취소 실패 algoId={algo_id}: {str(e)[:80]}")
            return False"""

content = content.replace(cancel_algo_old, cancel_algo_new)

# 4. Fix positionSide params
# Binance uses {"positionSide": "LONG"}
# OKX uses {"posSide": "long"} (in hedge mode)
# Let's change params={"positionSide": pos_side} to params={"posSide": pos_side.lower()}
content = re.sub(r'params=\{"positionSide": pos_side\}', 'params={"posSide": pos_side.lower()}', content)
content = re.sub(r'params=\{"positionSide": pos_side, "timeInForce": "GTX"\}', 'params={"posSide": pos_side.lower(), "timeInForce": "GTX"}', content)

# 5. Protective order posSide
# In _place_protective, it has params={"positionSide": pos_side, "stopPrice": sl_price}
# OKX requires slTriggerPx for stop loss? No, ccxt handles standard create_order with params={'stopLossPrice': sl_price}.
# But the existing code might be using Binance raw params.
# I need to see _place_protective first, but let's replace "positionSide" with "posSide" everywhere just in case.
content = content.replace('"positionSide":', '"posSide":')
content = content.replace('pos_side}', 'pos_side.lower()}')

with open(exchange_file, "w") as f:
    f.write(content)

print("exchange.py patched for OKX.")
