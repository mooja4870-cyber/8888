import re

filepath = "/Users/l/project/8401/core/trader.py"
with open(filepath, "r") as f:
    content = f.read()

old_guard = """        for p in positions:
            sym = p.get("symbol")"""
            
new_guard = """        # [Self-Healing Phase 3] 좀비 주문(Zombie Algo Orders) 청소기
        # 봇 재기동 시 포지션이 없는데 남아있는 알고리즘 주문(과거 TP/SL 찌꺼기)을 강제 청소한다.
        try:
            active_symbols = {p.get("symbol") for p in positions if p.get("symbol")}
            # 8401은 단일 거래소 클라이언트를 쓰므로 거래소 전체 pending algo orders를 조회하거나, 
            # 로컬 추적 중인 심볼에 대해 루프를 돌릴 수 있다.
            for sym in list(self.position_strategies.keys()) + list(self.recently_entered.keys()):
                if sym not in active_symbols:
                    try:
                        # 무포지션인데 남아있는 해당 종목 알고 주문 취소 시도
                        await self.client.cancel_algo_orders(sym)
                    except Exception as clean_err:
                        pass
        except Exception as z_err:
            logger.error(f"[ZOMBIE CLEANER] 좀비 주문 청소 중 예외: {z_err}")

        for p in positions:
            sym = p.get("symbol")"""

content = content.replace(old_guard, new_guard)

with open(filepath, "w") as f:
    f.write(content)

print("Phase 2/3 (Zombie Cleaner) injected successfully.")
