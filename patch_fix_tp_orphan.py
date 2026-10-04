import os

BOT_PORTS = ["8401", "8402", "8403", "8404", "8405", "8408", "8410"]
BASE_DIR = "/Users/l/project"

SCANNER_TARGET = """        # [v7.9.1 화이트리스트] 지정 시 해당 심볼만 스캔·진입 (블랙리스트·상위N보다 우선)
        whitelist = getattr(cfg_snap, "SYMBOL_WHITELIST", []) or []
        if whitelist:
            symbols = [s for s in symbols if s in whitelist]
            self._log_sync(f"[SCAN] 화이트리스트 한정: {whitelist} → {len(symbols)}개 스캔")
        else:
            # [블랙리스트] 금·은 등 제외 종목 스캔/진입 차단
            blacklist = getattr(cfg_snap, "SYMBOL_BLACKLIST", []) or []
            if blacklist:
                before = len(symbols)
                symbols = [s for s in symbols if s not in blacklist]
                removed = before - len(symbols)
                if removed:
                    self._log_sync(f"[SCAN] 블랙리스트 {removed}개 제외: {blacklist}")"""

SCANNER_REPLACE = """        # [BUG FIX] 현재 봇이 보유 중인 포지션은 화이트리스트 이탈이나 블랙리스트 지정과 무관하게 무조건 스캔 대상에 포함
        try:
            active_positions = await self.client.get_positions()
            active_symbols = [p["symbol"] for p in active_positions if p.get("symbol")]
        except Exception as e:
            self._log_sync(f"[ERR] 보유 포지션 조회 예외 발생: {e}")
            active_symbols = []

        # [v7.9.1 화이트리스트] 지정 시 해당 심볼만 스캔·진입 (블랙리스트·상위N보다 우선)
        whitelist = getattr(cfg_snap, "SYMBOL_WHITELIST", []) or []
        if whitelist:
            combined_whitelist = list(set(whitelist + active_symbols))
            symbols = [s for s in symbols if s in combined_whitelist]
            self._log_sync(f"[SCAN] 화이트리스트 한정(+보유종목 강제포함): {len(symbols)}개 스캔")
        else:
            # [블랙리스트] 금·은 등 제외 종목 스캔/진입 차단
            blacklist = getattr(cfg_snap, "SYMBOL_BLACKLIST", []) or []
            if blacklist:
                before = len(symbols)
                symbols = [s for s in symbols if s not in blacklist or s in active_symbols]
                removed = before - len(symbols)
                if removed:
                    self._log_sync(f"[SCAN] 블랙리스트 {removed}개 제외: {blacklist}")"""

ENGINE_TARGET = """    async def _evaluate_smart_exits(self, raw_positions):
        if self.cfg.MAX_HOLDING_HOURS > 0:"""

ENGINE_REPLACE = """    async def _evaluate_smart_exits(self, raw_positions):
        # [MANUAL TP FAIL-SAFE]
        # 트레일링 스탑이 꺼진 상태에서 TP를 이미 넘은(또는 오작동으로 미체결된) 포지션을 즉시 청산
        use_trailing = bool(getattr(self.cfg, "USE_TRAILING_STOP", False))
        if not use_trailing:
            tp_pct = float(getattr(self.cfg, "TAKE_PROFIT_PCT", 0.025))
            for p in list(raw_positions):
                sym = p.get("symbol")
                side = p.get("side")
                entry_price = float(p.get("entry_price") or 0.0)
                mark_price = float(p.get("mark_price") or 0.0)
                
                if entry_price > 0 and mark_price > 0:
                    pnl_pct = (mark_price - entry_price) / entry_price if side == "long" else (entry_price - mark_price) / entry_price
                    if pnl_pct >= tp_pct:
                        from core.logger import logger
                        logger.warning(f"[MANUAL TP FAIL-SAFE] {sym} {side} 현재가({mark_price})가 TP({tp_pct*100}%)를 이미 초과함(트레일링 비활성) → 즉시 익절")
                        await self.close_position_async(sym, side)
                        if p in raw_positions:
                            raw_positions.remove(p)

        if self.cfg.MAX_HOLDING_HOURS > 0:"""

for port in BOT_PORTS:
    bot_dir = os.path.join(BASE_DIR, port)
    
    scanner_path = os.path.join(bot_dir, "core", "scanner.py")
    if os.path.exists(scanner_path):
        with open(scanner_path, "r") as f:
            content = f.read()
        if SCANNER_TARGET in content:
            new_content = content.replace(SCANNER_TARGET, SCANNER_REPLACE)
            with open(scanner_path, "w") as f:
                f.write(new_content)
            print(f"Patched {port} scanner.py")
        else:
            print(f"Target not found in {port} scanner.py (might be already patched or different)")
            
    engine_path = os.path.join(bot_dir, "core", "engine.py")
    if os.path.exists(engine_path):
        with open(engine_path, "r") as f:
            content = f.read()
        if ENGINE_TARGET in content:
            new_content = content.replace(ENGINE_TARGET, ENGINE_REPLACE)
            with open(engine_path, "w") as f:
                f.write(new_content)
            print(f"Patched {port} engine.py")
        else:
            print(f"Target not found in {port} engine.py (might be already patched or different)")
