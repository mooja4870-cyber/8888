import re

path = "/Users/l/project/8407/core/exchange.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Modify _execute_with_retry
old_retry = """                if "-1021" in err_str and "1000ms ahead" in err_str:
                    logger.warning("[SYNC] Timestamp ahead error detected. Reloading time difference...")
                    try:
                        await self.exchange.load_time_difference()
                    except Exception:
                        pass

                if attempt == max_retries - 1:"""

new_retry = """                if "-1021" in err_str and "1000ms ahead" in err_str:
                    logger.warning("[SYNC] Timestamp ahead error detected. Reloading time difference...")
                    try:
                        await self.exchange.load_time_difference()
                    except Exception:
                        pass
                elif "-2010" in err_str or "-2022" in err_str or "Duplicate" in err_str:
                    # 중복 주문 오류 시 재시도하지 않고 즉시 예외 발생 (트레이더의 RECOVERY 로직으로 위임)
                    raise

                if attempt == max_retries - 1:"""

if old_retry in content:
    content = content.replace(old_retry, new_retry)

# 2. Modify _try_maker_entry signature
old_sig = """    async def _try_maker_entry(self, symbol: str, side: str, amount: float,
                               pos_side: str) -> Optional[Dict]:"""
new_sig = """    async def _try_maker_entry(self, symbol: str, side: str, amount: float,
                               pos_side: str, cid: str = None) -> Optional[Dict]:"""
content = content.replace(old_sig, new_sig)

# 3. Modify create_order inside _try_maker_entry
old_maker_order = """            order = await self._execute_with_retry(
                self.exchange.create_order,
                symbol=symbol, type="limit", side=side, amount=amount, price=px,
                params={"positionSide": pos_side, "timeInForce": "GTX"},
            )"""
new_maker_order = """            params = {"positionSide": pos_side, "timeInForce": "GTX"}
            if cid:
                params["newClientOrderId"] = cid
            order = await self._execute_with_retry(
                self.exchange.create_order,
                symbol=symbol, type="limit", side=side, amount=amount, price=px,
                params=params,
            )"""
content = content.replace(old_maker_order, new_maker_order)

# 4. Modify place_order
old_place = """            # 메이커 우선 진입. 미체결·거부·예외는 모두 None으로 돌아오며,
            # 그때는 아래 시장가 경로를 타므로 최악의 경우에도 현행과 동일하다.
            order = None
            if bool(getattr(CFG, "PREFER_MAKER_ORDER", False)):
                order = await self._try_maker_entry(symbol, side, amount, pos_side)

            if order is None:
                order = await self._execute_with_retry(
                    self.exchange.create_order,
                    symbol=symbol, type="market", side=side, amount=amount,
                    params={"positionSide": pos_side}
                )"""

new_place = """            import time, uuid
            cid = f"AGY-{int(time.time())}-{uuid.uuid4().hex[:6]}"

            # 메이커 우선 진입. 미체결·거부·예외는 모두 None으로 돌아오며,
            # 그때는 아래 시장가 경로를 타므로 최악의 경우에도 현행과 동일하다.
            order = None
            if bool(getattr(CFG, "PREFER_MAKER_ORDER", False)):
                order = await self._try_maker_entry(symbol, side, amount, pos_side, cid=cid)

            if order is None:
                order = await self._execute_with_retry(
                    self.exchange.create_order,
                    symbol=symbol, type="market", side=side, amount=amount,
                    params={"positionSide": pos_side, "newClientOrderId": cid}
                )"""
content = content.replace(old_place, new_place)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done patching 8407 exchange.")
