import re

path = "/Users/l/project/8410/core/exchange.py"
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
else:
    print("Could not find old_retry block.")

# 2. Modify place_order
old_maker = """            if use_maker:
                # 바이낸스 선물의 post-only는 timeInForce="GTX"(Good-Till-Crossing)다.
                # 즉시 체결될 가격이면 거래소가 주문을 거부한다 → 테이커가 될 일이 없다.
                order = await self._execute_with_retry(
                    self.exchange.create_order,
                    symbol=symbol, type="limit", side=side, amount=amount,
                    price=float(price),
                    params={"positionSide": pos_side, "timeInForce": "GTX"}
                )"""

new_maker = """            import uuid
            cid = f"AGY-{int(time.time())}-{uuid.uuid4().hex[:6]}"
            
            if use_maker:
                # 바이낸스 선물의 post-only는 timeInForce="GTX"(Good-Till-Crossing)다.
                # 즉시 체결될 가격이면 거래소가 주문을 거부한다 → 테이커가 될 일이 없다.
                order = await self._execute_with_retry(
                    self.exchange.create_order,
                    symbol=symbol, type="limit", side=side, amount=amount,
                    price=float(price),
                    params={"positionSide": pos_side, "timeInForce": "GTX", "newClientOrderId": cid}
                )"""

if old_maker in content:
    content = content.replace(old_maker, new_maker)
else:
    print("Could not find old_maker block.")

old_market = """            else:
                order = await self._execute_with_retry(
                    self.exchange.create_order,
                    symbol=symbol, type="market", side=side, amount=amount,
                    params={"positionSide": pos_side}
                )"""

new_market = """            else:
                order = await self._execute_with_retry(
                    self.exchange.create_order,
                    symbol=symbol, type="market", side=side, amount=amount,
                    params={"positionSide": pos_side, "newClientOrderId": cid}
                )"""

if old_market in content:
    content = content.replace(old_market, new_market)
else:
    print("Could not find old_market block.")

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done patching.")
