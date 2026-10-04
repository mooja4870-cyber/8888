import re
import os

bots = ["8403", "8404", "8405", "8408"]

for bot in bots:
    filepath = f"/Users/l/project/{bot}/core/trader.py"
    
    if not os.path.exists(filepath):
        print(f"[{bot}] trader.py not found.")
        continue
        
    with open(filepath, "r") as f:
        content = f.read()

    # --- Phase 1: Abnormal No-Position Detection ---
    old_init = """        self.position_partial_done: Dict[str, bool] = {}  # [Idea 2] 분할익절+본전스톱 완료 여부
        self.position_trade_modes: Dict[str, str] = {}    # 매매모드 ("역방향" / "순방향")
        self.global_cooldown_until: Optional[datetime] = None"""
        
    new_init = """        self.position_partial_done: Dict[str, bool] = {}  # [Idea 2] 분할익절+본전스톱 완료 여부
        self.position_trade_modes: Dict[str, str] = {}    # 매매모드 ("역방향" / "순방향")
        self.global_cooldown_until: Optional[datetime] = None
        
        # [Self-Healing Phase 1] 비정상적 무포지션 감지용
        self._consecutive_signal_failures: int = 0
        self._last_signal_time: Optional[datetime] = None"""
        
    if "self._consecutive_signal_failures" not in content:
        content = content.replace(old_init, new_init)

    old_time = """            if side == "sell" and not self.allow_short:
                logger.warning(f"[ENTRY BLOCK] {sig.symbol} — allow_short=False (Reverse)")
                return

            now_time = datetime.now()"""
            
    new_time = """            if side == "sell" and not self.allow_short:
                logger.warning(f"[ENTRY BLOCK] {sig.symbol} — allow_short=False (Reverse)")
                return

            # 시그널 수신 시간 기록
            now_time = datetime.now()
            if self._last_signal_time and (now_time - self._last_signal_time).total_seconds() > 3600:
                self._consecutive_signal_failures = 0  # 1시간 이상 신호 없었으면 초기화
            self._last_signal_time = now_time"""
            
    if "self._last_signal_time = now_time" not in content:
        content = content.replace(old_time, new_time)

    old_result = """                except Exception as recov_err:
                    logger.error(f"[ORDER RECOVERY FAILED] {sig.symbol} 포지션 복구 조회 실패: {recov_err}")

            if result:
                self.pending_entry_locks.pop(sig.symbol, None)"""
                
    new_result = """                except Exception as recov_err:
                    logger.error(f"[ORDER RECOVERY FAILED] {sig.symbol} 포지션 복구 조회 실패: {recov_err}")
                
                # 주문 실패 시 장애 카운트 증가
                self._consecutive_signal_failures += 1
                if self._consecutive_signal_failures >= 3:
                    logger.critical(f"[WATCHDOG] 진입 시그널 3회 연속 실패 감지 (잔고부족/API장애 등). 비정상적 무포지션 상태 규정 및 초기화 시도.")
                    from core.alert import send_telegram_alert
                    send_telegram_alert(f"🚨 *[{bot} 비정상적 무포지션 탐지]*\\n강력한 진입 시그널이 3회 연속 API 실패/가로막힘으로 체결되지 않았습니다. 봇 자체 점검이 필요합니다.")
                    self._consecutive_signal_failures = 0  # 알람 후 초기화
                    self.pending_entry_locks.clear()

            if result:
                self._consecutive_signal_failures = 0  # 진입 성공 시 초기화
                self.pending_entry_locks.pop(sig.symbol, None)"""
                
    if "self._consecutive_signal_failures += 1" not in content:
        content = content.replace(old_result, new_result)

    # --- Phase 2 & 3: Zombie Cleaner ---
    old_guard = """        for p in positions:
            sym = p.get("symbol")"""
            
    new_guard = """        # [Self-Healing Phase 3] 좀비 주문(Zombie Algo Orders) 청소기
        # 봇 재기동 시 포지션이 없는데 남아있는 알고리즘 주문(과거 TP/SL 찌꺼기)을 강제 청소한다.
        try:
            active_symbols = {p.get("symbol") for p in positions if p.get("symbol")}
            for sym in list(self.position_strategies.keys()) + list(self.recently_entered.keys()):
                if sym not in active_symbols:
                    try:
                        await self.client.cancel_algo_orders(sym)
                    except Exception:
                        pass
        except Exception as z_err:
            logger.error(f"[ZOMBIE CLEANER] 좀비 주문 청소 중 예외: {z_err}")

        for p in positions:
            sym = p.get("symbol")"""
            
    if "[Self-Healing Phase 3]" not in content:
        content = content.replace(old_guard, new_guard)

    with open(filepath, "w") as f:
        f.write(content)
        
    print(f"[{bot}] Patched successfully.")
