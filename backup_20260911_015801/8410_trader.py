"""
자동매매 실행 엔진 (비동기 엔터프라이즈 버전)
리스크 관리 + 포지션 관리 + 주문 실행 통합
"""
import asyncio
import logging
import os
import time
from typing import Optional, List, Dict
from datetime import datetime, date, timedelta, timezone

from core.exchange import BinanceClient
from core.strategy import Signal
from core.config import CFG
import core.stats as stats_store
from core.logger import log_trade as csv_log
from core.alert import send_telegram_alert

logger = logging.getLogger(__name__)


from core.position_state import PositionManager, PositionState

class AutoTrader:
    """
    비동기 자동매매 엔진
    Scanner.on_signal 콜백으로 신호를 받아 리스크 체크 후 실거래 실행
    """

    def __init__(self, client: BinanceClient):
        self.client = client
        self.cfg = CFG
        self._lock = None

        self.enabled: bool = False
        self.allow_long: bool = True
        self.allow_short: bool = True

        import sys
        if "pytest" not in sys.modules:
            _s = stats_store.load_stats()
            self.orders_today: int = _s.get("orders_today", 0)
            self.daily_pnl_usdt: float = _s.get("daily_pnl_usdt", 0.0)
        else:
            self.orders_today = 0
            self.daily_pnl_usdt = 0.0
            _s = {}
        self.trade_log: List[Dict] = []
        self._today: date = (datetime.utcnow() + timedelta(hours=9)).date()

        self.recently_entered: Dict[str, datetime] = {}
        self.pending_entry_locks: Dict[str, datetime] = {}
        self.position_strategies: Dict[str, str] = {}
        self.position_atr_activations: Dict[str, float] = {}  # [v2.14.3] 심볼별 ATR 동적 trailing activation
        self.position_atr_callbacks: Dict[str, float] = {}    # [Idea 3] 심볼별 ATR 적응형 trailing 콜백
        self.position_exit_profiles: Dict[str, str] = {}  # ATR 또는 SL/TP
        self.position_partial_done: Dict[str, bool] = {}  # [Idea 2] 분할익절+본전스톱 완료 여부
        self.position_open_time: Dict[str, datetime] = {} # [v9.7.0] 포지션 진입 시각 (타임아웃 탈출용)
        # [v9.9.3] 진입 시점의 매매방향(역방향/순방향). 청산 로그가 '청산 시점 현재값'을 쓰던 탓에
        # 같은 거래의 진입행·청산행 모드가 어긋나(진입=순방향/청산=역방향) 스위칭 이력이 은폐됐다.
        self.position_trade_modes: Dict[str, str] = {}
        self.global_cooldown_until: Optional[datetime] = None
        
        self.pos_manager = PositionManager(log_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), "position_transitions.log"))

        self.symbol_cooldown_until: Dict[str, datetime] = {}
        # [연패쿨다운] 동일종목 연속손실 추적
        self.symbol_loss_streak: Dict[str, int] = {}
        # [당일 연속손절 정지] 계좌 전체 연속 손절 → N회 시 당일 가동 강제 정지
        self._daily_consec_sl: int = 0
        self._consec_sl_date: date = self._today
        self._halted_by_consec_sl: bool = False
        self._daily_loss_alert_sent = False
        self._daily_profit_alert_sent = False
        self._last_risk_balance: Optional[Dict] = None

        # [v2.15.0] 영구 보존 복구 수행 (테스트 실행 환경에서는 복구 생략)
        import sys
        if "pytest" not in sys.modules:
            self.load_active_positions()
            self.load_cooldowns(_s)

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def enable(self):
        self.enabled = True
        logger.info("[TRADER] 자동매매 활성화 (Async)")

    def disable(self):
        self.enabled = False
        logger.info("[TRADER] 자동매매 비활성화")

    def trigger_global_cooldown(self, seconds: int = 60):
        self.global_cooldown_until = datetime.now() + timedelta(seconds=seconds)
        logger.info(f"[COOLDOWN] 글로벌 쿨다운 설정 완료 ({seconds}초간 새로운 진입 차단)")
        self.save_cooldowns()

    def register_trade_result(self, symbol: str, pnl: float):
        """[연패쿨다운] 청산 결과로 연패 추적. N회 연속손실 시 해당 종목 장기 진입차단.
        (백테스트 검증: 2연패 후 손실확률 60% → 8h 차단 시 누적수익 +8.8%)
        [당일 연속손절 정지] 계좌 전체 N연속 손절 시 당일 자동매매 강제 정지."""
        # ── 계좌 전체 당일 연속손절 정지 (MAX_CONSEC_SL_PER_DAY) ──
        max_consec = int(getattr(self.cfg, "MAX_CONSEC_SL_PER_DAY", 0) or 0)
        if max_consec > 0:
            today = (datetime.utcnow() + timedelta(hours=9)).date()
            if today != self._consec_sl_date:           # 날짜 변경 → 카운터·정지 해제
                self._consec_sl_date = today
                self._daily_consec_sl = 0
                self._halted_by_consec_sl = False
            if pnl < 0:
                self._daily_consec_sl += 1
                if self._daily_consec_sl >= max_consec and not self._halted_by_consec_sl:
                    self._halted_by_consec_sl = True
                    self.disable()
                    logger.warning(
                        f"[연속손절 정지] 당일 {self._daily_consec_sl}연속 손절 → 자동매매 당일 강제 정지 "
                        f"(MAX_CONSEC_SL_PER_DAY={max_consec}, 다음날 자동 재개)"
                    )
                    send_telegram_alert(
                        f"🛑 *[연속손절 정지]* 당일 {self._daily_consec_sl}연속 손절 도달 "
                        f"(한도 {max_consec}회) → 자동매매 당일 강제 정지. 다음날 자동 재개됩니다."
                    )
            else:
                self._daily_consec_sl = 0               # 익절 1회로 연속 끊김
            # [2026-09-04] 카운터가 바뀔 때마다 즉시 저장한다. 종전에는 저장 경로가
            # trigger_symbol_cooldown 안에만 있어, 종목별 쿨다운이 발동하지 않는 손실에서는
            # 카운터가 디스크에 남지 않았다 → 재기동 시 0으로 되돌아감.
            self.save_cooldowns()

        # ── 종목별 연패쿨다운 ──
        loss_n = int(getattr(self.cfg, "COOLDOWN_LOSS_COUNT", 2) or 0)
        hours = float(getattr(self.cfg, "COOLDOWN_HOURS", 8.0) or 0)
        if loss_n <= 0 or hours <= 0:
            return
        if pnl < 0:
            self.symbol_loss_streak[symbol] = self.symbol_loss_streak.get(symbol, 0) + 1
            if self.symbol_loss_streak[symbol] >= loss_n:
                self.trigger_symbol_cooldown(symbol, int(hours * 3600))
                logger.warning(f"[연패쿨다운] {symbol} {self.symbol_loss_streak[symbol]}연속손실 → {hours}시간 진입차단")
                self.symbol_loss_streak[symbol] = 0
        else:
            self.symbol_loss_streak[symbol] = 0
        # [2026-09-04] 종목별 연패 카운터도 메모리 전용이었다. 재기동하면 0으로 돌아가
        # "2연패 후 8시간 차단"이 영원히 발동하지 않았다(USELESS 3연패 실측).
        self.save_cooldowns()

    def trigger_symbol_cooldown(self, symbol: str, seconds: int = 60):
        self.symbol_cooldown_until[symbol] = datetime.now() + timedelta(seconds=seconds)
        logger.info(f"[COOLDOWN] {symbol} 종목별 쿨다운 설정 완료 ({seconds}초간 진입 차단)")
        self.save_cooldowns()

    def get_global_cooldown_left(self) -> float:
        """글로벌 쿨다운 잔여 시간(초)을 반환. 만료 시 0."""
        if self.global_cooldown_until:
            remaining = (self.global_cooldown_until - datetime.now()).total_seconds()
            return max(0.0, remaining)
        return 0.0

    def get_symbol_cooldown_left(self, symbol: str) -> float:
        """특정 종목의 쿨다운 잔여 시간(초)을 반환. 만료 시 0."""
        until = self.symbol_cooldown_until.get(symbol)
        if until:
            remaining = (until - datetime.now()).total_seconds()
            return max(0.0, remaining)
        return 0.0

    @property
    def cooldowns(self) -> Dict[str, datetime]:
        """현재 활성 종목별 쿨다운 딕셔너리 반환."""
        return self.symbol_cooldown_until

    def load_active_positions(self):
        try:
            import os
            import json
            if os.path.exists("data/active_positions.json"):
                with open("data/active_positions.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                for sym, val in data.items():
                    self.position_strategies[sym] = val.get("strategy_type", "Breakout")
                    self.position_atr_activations[sym] = val.get("atr_activation", getattr(self.cfg, 'TRAILING_ACTIVATE_PCT', 0.015))
                    self.position_atr_callbacks[sym] = val.get("atr_callback", getattr(self.cfg, 'TRAILING_CALLBACK_PCT', 0.012))
                    self.position_exit_profiles[sym] = val.get("exit_profile", "SL/TP")
                    self.position_partial_done[sym] = val.get("partial_done", False)
                    _pm = val.get("trade_mode", "")
                    if _pm:
                        self.position_trade_modes[sym] = _pm
                    if "open_time" in val:
                        try:
                            self.position_open_time[sym] = datetime.fromisoformat(val["open_time"])
                        except Exception:
                            self.position_open_time[sym] = datetime.now()
                    else:
                        self.position_open_time[sym] = datetime.now()
                logger.info(f"[PERSIST] 활성 포지션 상태 복구 완료 ({len(data)}건)")
        except Exception as e:
            logger.error(f"[PERSIST ERROR] 활성 포지션 상태 복구 실패: {e}")

    def save_active_positions(self):
        try:
            import os
            import json
            os.makedirs("data", exist_ok=True)
            data = {}
            for sym in list(self.position_strategies.keys()):
                data[sym] = {
                    "strategy_type": self.position_strategies.get(sym),
                    "atr_activation": self.position_atr_activations.get(sym, getattr(self.cfg, 'TRAILING_ACTIVATE_PCT', 0.015)),
                    "atr_callback": self.position_atr_callbacks.get(sym, getattr(self.cfg, 'TRAILING_CALLBACK_PCT', 0.012)),
                    "exit_profile": self.position_exit_profiles.get(sym, "SL/TP"),
                    "partial_done": self.position_partial_done.get(sym, False),
                    "open_time": self.position_open_time.get(sym, datetime.now()).isoformat(),
                    "trade_mode": self.position_trade_modes.get(sym, ""),
                }
            tmp = "data/active_positions.json.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, "data/active_positions.json")
            logger.info("[PERSIST] 활성 포지션 상태 저장 완료")
        except Exception as e:
            logger.error(f"[PERSIST ERROR] 활성 포지션 상태 저장 실패: {e}")

    async def guard_position_protection(self, positions: Optional[List[Dict]] = None) -> int:
        """
        거래소에 실재하는 포지션이 ① 로컬 추적에 등록돼 있고 ② 거래소측 보호주문(OCO)을
        갖고 있는지 점검하고, 빠진 것을 복구한다. 재무장한 건수를 반환한다.

        [도입 배경] 진입 후처리 중 예외(예: sl/tp 문자열에 :.6f 포맷 → TypeError)가 나면
        scanner의 종목 루프 try가 삼켜, 포지션은 열린 채 로컬 메타데이터와 거래소 OCO가
        **둘 다 없는 '고아'** 상태가 된다. 이때 최대보유시간·트레일링·분할익절·손절이
        전부 무동작이다. 실측: 8401 ALLO 35시간17분 / 8403 PUMP 60시간 손절 부재.

        헤드리스 러너(bot.py)는 QuantumEngine을 쓰지 않으므로 엔진 쪽 훅만으로는
        실매매 경로를 커버하지 못한다. 그래서 트레이더에 두고 양쪽에서 호출한다.
        """
        now = datetime.now().timestamp()
        if now - getattr(self, "_protect_guard_ts", 0.0) < 60.0:
            return 0
        self._protect_guard_ts = now

        try:
            if positions is None:
                positions = await self.client.get_positions()
        except Exception as e:
            logger.error(f"[PROTECT GUARD] 포지션 조회 실패: {e}")
            return 0
        # [2026-08-23] 보호주문을 수량 지정으로 바꾸면서 거래소 자동취소가 사라졌다.
        # 포지션이 사라진 종목에 남은 Algo 보호주문을 여기서 치운다.
        # **포지션이 0건일 때도 돌아야 하므로** 아래 조기 반환보다 먼저 둔다.
        sweep = getattr(self.client, "sweep_orphan_algo", None)
        if sweep:
            try:
                await sweep([p["symbol"] for p in (positions or [])])
            except Exception as e:
                logger.warning(f"[ALGO SWEEP] 실패: {str(e)[:80]}")

        if not positions:
            return 0

        try:
            self.sync_active_positions(positions)
        except Exception as e:
            logger.error(f"[PROTECT GUARD] 로컬 추적 동기화 실패: {e}")

        checker = getattr(self.client, "has_position_protection", None)
        rearm = getattr(self.client, "rearm_position_protection", None)
        if not checker or not rearm:
            return 0

        rearmed = 0
        for p in positions:
            sym = p.get("symbol")
            side = str(p.get("side") or "").lower()
            try:
                entry_price = float(p.get("entry_price") or p.get("entryPrice") or 0.0)
            except (TypeError, ValueError):
                entry_price = 0.0
            if not sym or side not in ("long", "short") or entry_price <= 0:
                continue
            try:
                protected = await checker(sym)
                # None = 확인 불가 → 중복 등록 위험이 있으므로 건드리지 않는다
                if protected is False:
                    logger.warning(
                        f"[PROTECT GUARD] {sym} {side.upper()} 보호주문 없음(무방비) → TP/SL 재무장 시도"
                    )
                    try:
                        mark = float(p.get("mark_price") or p.get("markPrice") or 0.0)
                    except (TypeError, ValueError):
                        mark = 0.0
                    # 거래소별로 rearm 시그니처가 다르다(바이낸스는 4번째가 sl_price).
                    #  위치 인자로 넘기면 현재가가 손절가로 들어가므로 지원 여부를 확인해
                    #  키워드로만 전달한다.
                    kwargs = {}
                    if mark > 0:
                        try:
                            import inspect
                            if "last_price" in inspect.signature(rearm).parameters:
                                kwargs["last_price"] = mark
                        except (TypeError, ValueError):
                            pass
                    if await rearm(sym, side, entry_price, **kwargs):
                        rearmed += 1
                        logger.info(f"[PROTECT GUARD] {sym} {side.upper()} 보호주문 재무장 완료")
                        send_telegram_alert(
                            f"🛡 *[보호주문 재무장]*\n종목: {sym}\n방향: {side.upper()}\n"
                            f"무방비 포지션을 감지해 TP/SL을 재설정했습니다."
                        )
                    else:
                        logger.error(
                            f"[PROTECT GUARD] {sym} {side.upper()} 보호주문 재무장 실패 — 수동 확인 필요"
                        )
            except Exception as e:
                logger.error(f"[PROTECT GUARD] {sym} 보호 점검 중 예외: {e}")
        return rearmed

    def sync_active_positions(self, actual_positions: List[Dict]):
        actual_symbols = {p["symbol"] for p in actual_positions}
        removed_any = False
        for sym in list(self.position_strategies.keys()):
            if sym not in actual_symbols:
                logger.info(f"[PERSIST] {sym} 포지션이 거래소에 존재하지 않음 (오프라인 청산 감지) → 상태 삭제")
                self.position_strategies.pop(sym, None)
                self.position_atr_activations.pop(sym, None)
                self.position_atr_callbacks.pop(sym, None)
                self.position_exit_profiles.pop(sym, None)
                self.position_partial_done.pop(sym, None)
                self.position_open_time.pop(sym, None)
                self.position_trade_modes.pop(sym, None)
                removed_any = True
        
        for p in actual_positions:
            sym = p["symbol"]
            if sym not in self.position_strategies:
                logger.warning(f"[RECONCILIATION] {sym} 거래소 포지션 로컬 상태 원천 복원(State Reconciliation) 수행")
                self.position_strategies[sym] = "DualBB"
                self.position_atr_activations[sym] = getattr(self.cfg, 'TRAILING_ACTIVATE_PCT', 0.015)
                self.position_atr_callbacks[sym] = getattr(self.cfg, 'TRAILING_CALLBACK_PCT', 0.006)
                self.position_exit_profiles[sym] = "SL/TP"
                self.position_partial_done[sym] = False  # [v9.8.0] 복원 포지션도 50% 분할 익절 및 BE Guard 100% 활성화!
                # 진입유실 방지를 위해 실제 체결 추정 시간(15분 전)으로 초기화하여 타임아웃 가드 및 본전 가드 정상 수혜
                self.position_open_time[sym] = datetime.now() - timedelta(minutes=15)
                removed_any = True
                
        if removed_any:
            self.save_active_positions()

    def load_cooldowns(self, stats_data: Dict):
        try:
            g_cd = stats_data.get("global_cooldown_until")
            if g_cd:
                dt = datetime.fromisoformat(g_cd)
                if dt > datetime.now():
                    self.global_cooldown_until = dt
                    logger.info(f"[PERSIST] 글로벌 쿨다운 복구 완료 (만료: {self.global_cooldown_until})")
            
            s_cd = stats_data.get("symbol_cooldown_until", {})
            for sym, iso_str in s_cd.items():
                dt = datetime.fromisoformat(iso_str)
                if dt > datetime.now():
                    self.symbol_cooldown_until[sym] = dt
                    logger.info(f"[PERSIST] {sym} 종목별 쿨다운 복구 완료 (만료: {dt})")

            # [2026-09-04] 당일 연속손절 상태 복구 — 재기동으로 정지가 풀리던 문제.
            # 저장된 날짜가 오늘과 다르면 복구하지 않는다(다음날 자동 재개 규칙 유지).
            try:
                _d = stats_data.get("consec_sl_date")
                if _d and date.fromisoformat(_d) == (datetime.utcnow() + timedelta(hours=9)).date():
                    self._consec_sl_date = date.fromisoformat(_d)
                    self._daily_consec_sl = int(stats_data.get("daily_consec_sl", 0) or 0)
                    self._halted_by_consec_sl = bool(stats_data.get("halted_by_consec_sl", False))
                    if self._halted_by_consec_sl:
                        logger.warning(
                            f"[PERSIST] 당일 연속손절 정지 상태 복구 — {self._daily_consec_sl}연속 손절로 "
                            f"자동매매 정지 유지 (다음날 자동 재개)")
                    elif self._daily_consec_sl:
                        logger.info(f"[PERSIST] 당일 연속손절 카운터 복구: {self._daily_consec_sl}회")
                _sls = stats_data.get("symbol_loss_streak") or {}
                if _sls:
                    self.symbol_loss_streak.update({k: int(v) for k, v in _sls.items()})
                    logger.info(f"[PERSIST] 종목별 연패 카운터 복구: {dict(list(_sls.items())[:5])}")
            except Exception as _ce:
                logger.warning(f"[PERSIST] 연속손절 상태 복구 실패(무시): {_ce}")
        except Exception as e:
            logger.error(f"[PERSIST ERROR] 쿨다운 복구 실패: {e}")

    def save_cooldowns(self):
        try:
            data = stats_store.load_stats()
            now = datetime.now()
            self.symbol_cooldown_until = {sym: dt for sym, dt in self.symbol_cooldown_until.items() if dt > now}
            
            data["global_cooldown_until"] = self.global_cooldown_until.isoformat() if self.global_cooldown_until and self.global_cooldown_until > now else None
            data["symbol_cooldown_until"] = {sym: dt.isoformat() for sym, dt in self.symbol_cooldown_until.items()}
            # [2026-09-04] 당일 연속손절 카운터·정지 플래그도 함께 보존한다.
            # 종전에는 메모리에만 있어 **재기동 한 번에 통째로 사라졌다.**
            # 8410은 8888 워치독 감시 대상이라 다운 감지 시 자동 재기동되고,
            # 수동 재기동도 잦다. 그 결과 MAX_CONSEC_SL_PER_DAY=3을 걸어두고도
            # 9연패가 그대로 진행됐다(2026-09-03 16:12 ~ 09-04 07:33 실측).
            # 정지는 '당일' 단위이므로 날짜와 함께 저장해야 다음날 정상 해제된다.
            data["daily_consec_sl"] = int(self._daily_consec_sl)
            data["consec_sl_date"] = self._consec_sl_date.isoformat() if self._consec_sl_date else None
            data["halted_by_consec_sl"] = bool(self._halted_by_consec_sl)
            data["symbol_loss_streak"] = {k: int(v) for k, v in (self.symbol_loss_streak or {}).items() if v}
            stats_store.save_stats(data)
            logger.info("[PERSIST] 쿨다운 상태 stats.json에 영구 보존 완료")
        except Exception as e:
            logger.error(f"[PERSIST ERROR] 쿨다운 상태 저장 실패: {e}")

    async def on_signal(self, sig: Signal):
        # 🔴 진입 차단 진단용 로깅
        logger.info(f"[SIGNAL] {sig.symbol} {sig.direction.upper()} 신호 수신 (strength={sig.strength})")

        # [수정됨] 청개구리 역매매 동적 반전 로직 적용
        is_bluefrog = getattr(self.cfg, "USE_BLUEFROG", False)
        direction = sig.direction
        if is_bluefrog and direction in ["long", "short"]:
            raw_dir = direction
            direction = "short" if direction == "long" else "long"
            sig.direction = direction
            logger.info(f"[🐸 청개구리 역매매] 신호 방향 반전: {raw_dir.upper()} ➡️ {direction.upper()}")

        
        # [방향 게이트] 추세를 거스르는 진입을 막는다.
        
        # 역매매(청개구리) 반전이 끝난 **최종 방향**에 걸어야 한다. 전략 단계에서 걸면
        
        # 반전 때문에 정반대로 작동한다.
        
        if getattr(self.cfg, "USE_MARKET_GATE", False) and sig.direction in ("long", "short"):
        
            td = int(getattr(sig, "trend_dir", 0) or 0)
        
            if td != 0 and (td > 0) != (sig.direction == "long"):
        
                logger.info(f"[GATE BLOCK] {sig.symbol} {sig.direction.upper()} — 추세 역행(trend={td})")
        
                return
        
        side = "buy" if sig.direction == "long" else "sell"

        if sig.direction == "none":
            logger.debug(f"[SKIP] {sig.symbol} — direction=none")
            return

        async with self.lock:
            # [데드락 방지] 날짜 변경 확인을 trader.enabled 검사보다 먼저 수행하여 전일 정지 자동 해제 보장
            self._reset_daily_if_needed()

            if not self.enabled:
                logger.warning(f"[ENTRY BLOCK] {sig.symbol} — trader disabled")
                return

            try:
                passed, reason = await self._risk_check(sig)
                if not passed:
                    logger.warning(f"[RISK BLOCK] {sig.symbol} — {reason}")
                    self._log_trade(sig, status="BLOCKED", reason=reason)
                    return
                logger.info(f"[RISK OK] {sig.symbol} 리스크 체크 통과")
            except Exception as e:
                logger.error(f"[RISK ERROR] {sig.symbol} 리스크 체크 중 예외 발생: {e}")
                self._log_trade(sig, status="FAILED", reason=f"API 조회 오류 ({e})")
                return

            if side == "buy" and not self.allow_long:
                logger.warning(f"[ENTRY BLOCK] {sig.symbol} — allow_long=False (Reverse)")
                return
            if side == "sell" and not self.allow_short:
                logger.warning(f"[ENTRY BLOCK] {sig.symbol} — allow_short=False (Reverse)")
                return

            now_time = datetime.now()
            # [v2.15.0] recently_entered를 정적 120초 대신 거래소 싱크 확인 기반으로 동적 관리
            try:
                positions = await self.client.get_positions()
                symbols_held = {p["symbol"] for p in positions}
                
                recently_entered_changed = False
                for sym in list(self.recently_entered.keys()):
                    if sym in symbols_held:
                        logger.info(f"[SYNC] {sym} 포지션 거래소 반영 확인 → recently_entered 락 해제")
                        self.recently_entered.pop(sym, None)
                        recently_entered_changed = True
                    else:
                        # API 누락/취소 대비 10분 강제 락 해제 가드
                        ts = self.recently_entered[sym]
                        if (now_time - ts).total_seconds() > 600:
                            logger.warning(f"[SYNC TIMEOUT] {sym} 10분간 포지션 미감지 → recently_entered 락 강제 해제")
                            self.recently_entered.pop(sym, None)
                            recently_entered_changed = True

                # 진입 주문 in-flight 락이 비정상적으로 남는 경우 자동 해제 (2분)
                for sym in list(self.pending_entry_locks.keys()):
                    lock_ts = self.pending_entry_locks[sym]
                    if (now_time - lock_ts).total_seconds() > 120:
                        logger.warning(f"[ENTRY LOCK TIMEOUT] {sym} pending entry lock 120초 초과 → 자동 해제")
                        self.pending_entry_locks.pop(sym, None)
                        recently_entered_changed = True
                
                if recently_entered_changed:
                    try:
                        from core.engine import QuantumEngine
                        QuantumEngine.get_instance().save_engine_states()
                    except Exception as persist_err:
                        logger.error(f"recently_entered 변경 저장 실패: {persist_err}")

                if sig.symbol in symbols_held or sig.symbol in self.recently_entered or sig.symbol in self.pending_entry_locks:
                    logger.info(f"[ENTRY BLOCK] {sig.symbol} — 이미 포지션 보유 또는 진입 주문 전송 중")
                    logger.debug(f"  - symbols_held: {sig.symbol in symbols_held}")
                    logger.debug(f"  - recently_entered: {sig.symbol in self.recently_entered}")
                    logger.debug(f"  - pending_entry_locks: {sig.symbol in self.pending_entry_locks}")
                    return

                effective_count = len(symbols_held) + len(self.recently_entered)
                if effective_count >= self.cfg.MAX_POSITIONS:
                    logger.warning(f"[ENTRY BLOCK] {sig.symbol} — 최대 포지션 수 도달: {effective_count}/{self.cfg.MAX_POSITIONS}")
                    return

                logger.info(f"[ENTRY OK] {sig.symbol} 포지션 체크 통과 (현재 {effective_count}/{self.cfg.MAX_POSITIONS})")
            except Exception as e:
                logger.error(f"[TRADER ERROR] 포지션 체크 중 예외 발생: {e}")
                self._log_trade(sig, status="FAILED", reason=f"포지션 조회 오류 ({e})")
                return

            # 주문 API 호출 전에 선(先)락을 걸어 다중 인스턴스/지연 상황의 중복 진입 가능성 완화
            self.pending_entry_locks[sig.symbol] = datetime.now()
            
            # [Dynamic Compounding Margin]
            margin_source = "fixed"
            if getattr(self.cfg, "USE_AUTO_COMPOUND", False):
                logger.info(f"[MARGIN] AUTO_COMPOUND 활성화 감지")
                balance = self._last_risk_balance
                margin_source = "compound_cached"
                if not isinstance(balance, dict):
                    try:
                        balance = await self.client.get_balance()
                        margin_source = "compound_live"
                        logger.info(f"[MARGIN] 실시간 잔고 조회: {balance}")
                    except Exception as e:
                        logger.error(f"[COMPOUND ERROR] 잔고 조회 실패로 진입 차단: {e}")
                        self.pending_entry_locks.pop(sig.symbol, None)
                        self._log_trade(sig, status="FAILED", reason=f"복리 잔고 조회 실패 ({e})")
                        return

                total_bal = float(balance.get("total", 0.0) or 0.0)
                if total_bal <= 0:
                    logger.error(f"[COMPOUND ERROR] 총잔고(total)={total_bal} 비정상으로 진입 차단")
                    self.pending_entry_locks.pop(sig.symbol, None)
                    self._log_trade(sig, status="FAILED", reason=f"복리 잔고값 비정상({total_bal})")
                    return

                compound_pct = float(getattr(self.cfg, "AUTO_COMPOUND_PCT", 18.0))
                margin_usdt = round(total_bal * (compound_pct / 100.0) * getattr(self.cfg, 'EQUITY_SCALE_FACTOR', 1.0), 2)
                logger.info(
                    f"[COMPOUND OK] 자동 복리 마진: 총 잔고 ${total_bal:.2f}, 비율 {compound_pct:.2f}% "
                    f"→ 1회 진입 증거금 ${margin_usdt:.2f}"
                )
            else:
                margin_usdt = self.cfg.MARGIN_USDT * getattr(self.cfg, 'EQUITY_SCALE_FACTOR', 1.0)
                logger.info(f"[MARGIN] 고정 모드: ${margin_usdt:.2f}")

            logger.info(
                f"[MARGIN DECISION] symbol={sig.symbol} source={margin_source} "
                f"margin={margin_usdt:.2f} auto_compound={getattr(self.cfg, 'USE_AUTO_COMPOUND', False)} "
                f"compound_pct={float(getattr(self.cfg, 'AUTO_COMPOUND_PCT', 18.0)):.2f} "
                f"fixed_margin={float(getattr(self.cfg, 'MARGIN_USDT', 0.0)):.2f}"
            )

            has_abs_sltp = (
                getattr(sig, "sl_price", 0.0) > 0 and
                getattr(sig, "tp_price", 0.0) > 0 and
                sig.close > 0
            )
            has_swing_sltp = (
                getattr(sig, "swing_sl_price", 0.0) > 0 and
                getattr(sig, "tp1_price", 0.0) > 0 and
                sig.close > 0
            )
            
            # ── [M4] 변동성 타게팅 포지션 사이징 ──
            risk_pct = float(getattr(self.cfg, "RISK_PER_TRADE_PCT", 0.01))
            if risk_pct > 0:
                try:
                    balance = await self.client.get_balance()
                    total_bal = float(balance.get("total", 0.0) or 0.0)
                    if total_bal > 0:
                        # [M4] risk_pct는 0.01 = 1% 로 해석 (기존 100나누기 버그 수정)
                        risk_usdt = total_bal * risk_pct
                        
                        # [M5] 레짐 프로파일 파라미터 적용
                        profile = {}
                        if getattr(self.cfg, "USE_REGIME_FILTER", False) and getattr(sig, "regime", "Unknown") != "Unknown":
                            regime_profiles = getattr(self.cfg, "REGIME_PROFILES", {})
                            profile = regime_profiles.get(sig.regime, {})
                            # 컨텍스트에 저장하여 청산(TP/SL) 엔진도 참조 가능하게 함
                            self.pos_manager.contexts[sig.symbol] = {"regime": sig.regime, "profile": profile}
                        else:
                            # 레짐 미사용 시 컨텍스트 초기화
                            self.pos_manager.contexts.pop(sig.symbol, None)
                        
                        # 스탑 거리 계산
                        if has_abs_sltp:
                            sl_pct = abs(sig.close - sig.sl_price) / sig.close
                        elif has_swing_sltp:
                            sl_pct = abs(sig.close - sig.swing_sl_price) / sig.close
                        elif sig.atr > 0 and sig.close > 0:
                            k = float(profile.get("SIZING_K", getattr(self.cfg, "SIZING_K", 3.0)))
                            sl_pct = (k * sig.atr) / sig.close
                        else:
                            sl_pct = getattr(self.cfg, "STOP_LOSS_PCT", 0.02)
                            
                        # 최소 SL 하한 적용 (초협폭 방지)
                        _sl_floor = float(profile.get("DBB_MIN_SL_PCT", getattr(self.cfg, "DBB_MIN_SL_PCT", 0.003)))
                        sl_pct = max(sl_pct, _sl_floor)
                        
                        # 목표 리스크를 맞추기 위한 마진 계산
                        lev = float(self.cfg.LEVERAGE)
                        calc_margin_usdt = risk_usdt / (sl_pct * lev)
                        
                        # 최대 Notional 제한 적용
                        max_notional = float(getattr(self.cfg, "MAX_NOTIONAL_PER_POS", 5000.0))
                        max_margin_for_notional = max_notional / lev
                        calc_margin_usdt = min(calc_margin_usdt, max_margin_for_notional)
                        
                        # 30% 캡 방어
                        margin_cap = total_bal * 0.30
                        calc_margin_usdt = min(calc_margin_usdt, margin_cap)
                        
                        calc_margin_usdt = max(1.0, calc_margin_usdt)
                        
                        margin_usdt = round(calc_margin_usdt, 2)
                        margin_source = "risk_based_m4"
                        logger.info(
                            f"[M4 SIZING] {sig.symbol} 잔고=${total_bal:.2f}, "
                            f"리스크={risk_pct*100:.2f}%, SL거리={sl_pct*100:.2f}% "
                            f"→ 증거금=${margin_usdt:.2f} (Notional: ${margin_usdt*lev:.2f})"
                        )
                except Exception as e:
                    logger.warning(f"[M4 SIZING] 마진 계산 실패, 이전 마진 사용: {e}")

            # --- [Step 3] Danger Zone Position Sizing (Meta-Labeling Soft Filter) ---
            if getattr(self.cfg, "USE_DANGER_ZONE_SIZING", True):
                try:
                    ticker = await self.client.get_ticker(sig.symbol)
                    if ticker:
                        last_px = float(ticker.get('last', 0))
                        high24 = float(ticker.get('high', 0))
                        low24 = float(ticker.get('low', 0))
                        if high24 > 0 and low24 > 0 and high24 > low24:
                            pos_24h = (last_px - low24) / (high24 - low24)
                            is_danger = False
                            if sig.direction == "long" and 0.80 < pos_24h <= 0.95:
                                is_danger = True
                            elif sig.direction == "short" and 0.05 <= pos_24h < 0.20:
                                is_danger = True
                            
                            if is_danger:
                                old_margin = margin_usdt
                                margin_usdt = round(margin_usdt * 0.5, 2)
                                logger.warning(f"⚠️ [DANGER ZONE SIZING] {sig.direction.upper()} 진입 위험구역(pos: {pos_24h*100:.1f}%). 시드 투입량 절반(0.5x) 축소: {old_margin} -> {margin_usdt}")
                                send_telegram_alert(f"⚠️ *[DANGER ZONE]* {sig.symbol} {sig.direction.upper()} 진입 시그널이 24시간 변위 위험구역({pos_24h*100:.1f}%)에 해당하여 시드 투입량을 50% 축소합니다. ({old_margin} -> {margin_usdt})")
                except Exception as e:
                    logger.warning(f"[DANGER ZONE SIZING] 변위 확인 예외: {e}")

            if margin_usdt < 1.0:
                logger.warning(f"[SKIP] 증거금 설정 오류 (최소 $1): {margin_usdt:.2f} USDT")
                # [v8.5.0] 선락 해제 누락 수정: 미해제 시 120초 타임아웃까지 해당 심볼 진입 차단됨
                self.pending_entry_locks.pop(sig.symbol, None)
                self._log_trade(sig, status="BLOCKED", reason=f"증거금 최소치 미달 (${margin_usdt:.2f} < $1)")
                return

            # ── SL/TP 계산 ──
            if has_swing_sltp:
                dynamic_sl_pct = abs(sig.close - sig.swing_sl_price) / sig.close
                dynamic_tp_pct = abs(sig.tp1_price - sig.close) / sig.close
                
                if side == "sell" and getattr(self.cfg, "ASYMMETRIC_SHORT_TP", 1.0) != 1.0:
                    dynamic_tp_pct *= self.cfg.ASYMMETRIC_SHORT_TP
                
                # [v9.9.6] SL 폭 하한 — 수수료/스프레드만으로 즉시 손절되는 초협폭 SL 차단.
                # 왕복 테이커 수수료(약 0.10%)보다 좁은 손절폭은 손실이 수수료의 2배가 되어
                # 승률과 무관하게 기대값이 음수가 된다. DualBB 경로에만 있던 가드를 이식.
                # 하한 적용 시 원래 손익비(RR)를 보존하도록 TP도 같은 배율로 확대한다.
                _sl_floor = float(getattr(self.cfg, "MIN_SL_PCT",
                                          getattr(self.cfg, "DBB_MIN_SL_PCT", 0.005)))
                if _sl_floor > 0 and 0 < dynamic_sl_pct < _sl_floor:
                    _rr_keep = (dynamic_tp_pct / dynamic_sl_pct) if dynamic_sl_pct > 0 \
                        else float(getattr(self.cfg, "DBB_TP_RR", 2.0))
                    _tp_new = _sl_floor * _rr_keep
                    logger.info(
                        f"[SL FLOOR] {sig.symbol} SL {dynamic_sl_pct*100:.3f}% → {_sl_floor*100:.2f}% "
                        f"/ TP {dynamic_tp_pct*100:.3f}% → {_tp_new*100:.3f}% (RR 1:{_rr_keep:.2f} 유지)"
                    )
                    dynamic_sl_pct = _sl_floor
                    dynamic_tp_pct = _tp_new

                # [v9.9.6] TP 폭 하한 — 왕복 수수료를 덮지 못하는 익절은 이겨도 손해다
                _tp_floor = float(getattr(self.cfg, "MIN_TP_PCT", 0.0))
                if _tp_floor > 0 and dynamic_tp_pct < _tp_floor:
                    logger.info(
                        f"[TP FLOOR] {sig.symbol} TP {dynamic_tp_pct*100:.3f}% → 하한 {_tp_floor*100:.2f}%로 확대"
                    )
                    dynamic_tp_pct = _tp_floor

                _sl_cap = getattr(self.cfg, "DYNAMIC_SL_CAP_PCT", 0.05)
                if _sl_cap > 0 and dynamic_sl_pct > _sl_cap:
                    ratio = _sl_cap / dynamic_sl_pct
                    dynamic_sl_pct = _sl_cap
                    dynamic_tp_pct = dynamic_tp_pct * ratio

                logger.info(
                    f"[{sig.strategy_type} SL/TP] {sig.symbol} 시그널 내장 가격 기반: "
                    f"SL={sig.swing_sl_price:.4f}({dynamic_sl_pct*100:.3f}%) "
                    f"TP={sig.tp1_price:.4f}({dynamic_tp_pct*100:.3f}%)"
                )
            elif has_abs_sltp:
                sl_width = abs(sig.close - sig.sl_price)
                dynamic_sl_pct = sl_width / sig.close
                tp_width = abs(sig.tp_price - sig.close)
                dynamic_tp_pct = tp_width / sig.close
                _sl_cap = getattr(self.cfg, "DYNAMIC_SL_CAP_PCT", 0.05)
                if _sl_cap > 0 and dynamic_sl_pct > _sl_cap:
                    ratio = _sl_cap / dynamic_sl_pct
                    dynamic_sl_pct = _sl_cap
                    dynamic_tp_pct = dynamic_tp_pct * ratio
                logger.info(
                    f"[W/M SL/TP] {sig.symbol} 절대가격 기반: "
                    f"SL={sig.sl_price:.4f}({dynamic_sl_pct*100:.3f}%) "
                    f"TP={sig.tp_price:.4f}({dynamic_tp_pct*100:.3f}%)"
                )
            elif sig.strategy_type == "QAR-ARE":
                # [2026-08-26] QAR-ARE Triple Barrier (2.5 ATR TP / 1.2 ATR SL)
                sl_abs = float(getattr(sig, "swing_sl_price", 0.0) or 0.0)
                tp_abs = float(getattr(sig, "tp1_price", 0.0) or 0.0)
                if sl_abs > 0 and sig.close > 0:
                    dynamic_sl_pct = abs(sig.close - sl_abs) / sig.close
                else:
                    dynamic_sl_pct = getattr(self.cfg, "STOP_LOSS_PCT", 0.012)
                if tp_abs > 0 and sig.close > 0:
                    dynamic_tp_pct = abs(tp_abs - sig.close) / sig.close
                else:
                    dynamic_tp_pct = dynamic_sl_pct * 2.08
                logger.info(
                    f"[QAR-ARE Triple Barrier] {sig.symbol} SL={dynamic_sl_pct*100:.3f}% "
                    f"TP={dynamic_tp_pct*100:.3f}% (RR {dynamic_tp_pct/dynamic_sl_pct:.2f}:1)"
                )
            elif sig.strategy_type == "DualBB":
                # [8405 복제·순수 RR 1:2] SL=로컬극점(절대가), TP=SL폭×RR 고정.
                # SL CAP을 분기 내부에서 적용하고 TP를 캡된 SL 기준으로 재계산 → 캡 발동 시에도 RR 정확.
                _rr = float(getattr(self.cfg, "DBB_TP_RR", 2.0))
                sl_abs = float(getattr(sig, "swing_sl_price", 0.0) or 0.0)
                if sl_abs > 0 and sig.close > 0:
                    dynamic_sl_pct = abs(sig.close - sl_abs) / sig.close
                else:
                    dynamic_sl_pct = getattr(self.cfg, "STOP_LOSS_PCT", 0.01)
                # [v8.5.0] SL 폭 하한: 스윙 극점이 현재가에 붙어 있으면 수수료/스프레드만으로
                # 즉시 손절되는 초협폭 SL 차단 (ATR 경로의 0.3% 하한과 동일 수준)
                _sl_floor = float(getattr(self.cfg, "DBB_MIN_SL_PCT", 0.003))
                if _sl_floor > 0 and dynamic_sl_pct < _sl_floor:
                    logger.info(
                        f"[DUALBB SL FLOOR] {sig.symbol} SL {dynamic_sl_pct*100:.3f}% → 하한 {_sl_floor*100:.2f}%로 확대 (TP도 RR 유지 재계산)"
                    )
                    dynamic_sl_pct = _sl_floor
                _sl_cap = getattr(self.cfg, "DYNAMIC_SL_CAP_PCT", 0.05)
                if _sl_cap and _sl_cap > 0 and dynamic_sl_pct > _sl_cap:
                    logger.info(f"[DUALBB SL CAP] {sig.symbol} SL {dynamic_sl_pct*100:.2f}% → 상한 {_sl_cap*100:.2f}% (RR 유지 위해 TP 재계산)")
                    dynamic_sl_pct = _sl_cap
                dynamic_tp_pct = dynamic_sl_pct * _rr   # 고정 RR 1:2 보장
                logger.info(
                    f"[DUALBB SL/TP] {sig.symbol} SL={dynamic_sl_pct*100:.3f}% "
                    f"TP={dynamic_tp_pct*100:.3f}% (고정 RR 1:{_rr:.1f})"
                )
            elif sig.strategy_type == "Mean Reversion":
                dynamic_sl_pct = getattr(self.cfg, "MR_STOP_LOSS_PCT", 0.02)
                if sig.bb_mid > 0 and sig.close > 0:
                    dynamic_tp_pct = abs(sig.bb_mid - sig.close) / sig.close
                    dynamic_tp_pct = max(0.003, min(0.03, dynamic_tp_pct))
                else:
                    dynamic_tp_pct = getattr(self.cfg, "MR_TAKE_PROFIT_PCT", 0.01)
                logger.info(f"[MEAN REVERSION SL/TP] {sig.symbol} -> SL={dynamic_sl_pct*100:.2f}%, TP={dynamic_tp_pct*100:.2f}%")
            else:
                if getattr(self.cfg, "USE_DYNAMIC_SLTP", False) and sig.atr > 0 and sig.close > 0:
                    atr_pct = sig.atr / sig.close
                    # [v3.0.0] 동적 손익절 최소 하한선 가드 장치 도입 (SL 최소 0.3%, TP 최소 0.5%)
                    dynamic_sl_pct = max(0.003, atr_pct * getattr(self.cfg, "ATR_SL_MULT", 1.5))
                    dynamic_tp_pct = max(0.005, atr_pct * getattr(self.cfg, "ATR_TP_MULT", 2.0))
                    logger.info(f"[DYNAMIC SL/TP] {sig.symbol} ATR={sig.atr:.4f} ({atr_pct*100:.2f}%) -> SL={dynamic_sl_pct*100:.2f}%, TP={dynamic_tp_pct*100:.2f}%")
                else:
                    dynamic_sl_pct = getattr(self.cfg, "STOP_LOSS_PCT", 0.01)
                    dynamic_tp_pct = getattr(self.cfg, "TAKE_PROFIT_PCT", 0.015)

            # [SL 상한] W/M 전략은 위 has_abs_sltp 블록에서 이미 캡 적용, 이 블록은 폴백 전략용
            if not has_abs_sltp:
                _sl_cap = getattr(self.cfg, "DYNAMIC_SL_CAP_PCT", 0.05)
                if _sl_cap and _sl_cap > 0 and dynamic_sl_pct > _sl_cap:
                    logger.info(
                        f"[SL CAP] {sig.symbol} 손절폭 {dynamic_sl_pct*100:.2f}% → 상한 {_sl_cap*100:.2f}%로 제한"
                    )
                    dynamic_sl_pct = _sl_cap

            # 🔴 최종 진입 로깅
            logger.info(
                f"[FINAL ENTRY] {sig.symbol} {side.upper()} 주문 실행 예정: "
                f"margin=${margin_usdt:.2f} SL={dynamic_sl_pct*100:.2f}% TP={dynamic_tp_pct*100:.2f}%"
            )

            result = None
            try:
                logger.info(f"[ORDER PLACE] {sig.symbol} place_order 호출 중...")
                result = await self.client.place_order(
                    symbol=sig.symbol,
                    side=side,
                    margin_usdt=margin_usdt,
                    stop_loss_pct=dynamic_sl_pct,
                    take_profit_pct=dynamic_tp_pct
                )
                logger.info(f"[ORDER RESULT] {sig.symbol} 주문 결과: {result}")
            except Exception as e:
                logger.error(f"[ORDER TIMEOUT/ERROR] {sig.symbol} 진입 주문 API 에러 발생: {e}")
                # 타임아웃/에러 시 거래소 포지션을 즉시 조회하여 실제 체결 여부 검증
                await asyncio.sleep(2.0)  # 체결 반영 싱크 대기
                try:
                    positions = await self.client.get_positions()
                    matching_pos = [p for p in positions if p["symbol"] == sig.symbol and p["side"] == ("long" if side == "buy" else "short")]
                    if matching_pos:
                        pos = matching_pos[0]
                        logger.warning(f"[ORDER RECOVERY] {sig.symbol} API 에러가 발생했으나 실제 거래소에 포지션이 체결되어 있음 감지! 복구를 진행합니다.")
                        result = {
                            "order_id": f"RECOV-{int(time.time())}",
                            "symbol": sig.symbol,
                            "side": pos["side"],
                            "entry_price": pos["entry_price"],
                            "amount": pos["size"],
                            "sl_price": pos["entry_price"] * (1 - dynamic_sl_pct) if side == "buy" else pos["entry_price"] * (1 + dynamic_sl_pct),
                            "tp_price": pos["entry_price"] * (1 + dynamic_tp_pct) if side == "buy" else pos["entry_price"] * (1 - dynamic_tp_pct),
                            "usdt_margin": pos["margin"],
                        }
                    else:
                        logger.info(f"[ORDER RECOVERY] {sig.symbol} 실제 거래소에도 포지션이 체결되지 않음 확인 완료.")
                except Exception as recov_err:
                    logger.error(f"[ORDER RECOVERY FAILED] {sig.symbol} 포지션 복구 조회 실패: {recov_err}")

            if result:
                self.pending_entry_locks.pop(sig.symbol, None)
                self.recently_entered[sig.symbol] = datetime.now()
                self.position_strategies[sig.symbol] = sig.strategy_type
                self.position_open_time[sig.symbol] = datetime.now()
                # [v9.9.3] 진입 시점 매매방향을 고정 보존 → 청산 로그가 이 값을 참조한다
                self.position_trade_modes[sig.symbol] = "역방향" if bool(getattr(self.cfg, "USE_BLUEFROG", True)) else "순방향"
                self.position_exit_profiles[sig.symbol] = "ATR" if bool(getattr(self.cfg, "USE_DYNAMIC_SLTP", False)) else "SL/TP"
                # [v2.14.3 개선④] ATR 기반 동적 trailing activation 저장
                # 심볼별 변동성을 반영하여 트레일링 스탑 조기첩산 방지
                self.position_partial_done[sig.symbol] = False  # [Idea 2] 분할익절 미완료로 초기화
                if sig.atr > 0 and sig.close > 0:
                    atr_pct = sig.atr / sig.close
                    # 활성화 기준: ATR의 1.5배 (컴파 1.0~5.0% 클램핑)
                    dynamic_activation = max(0.010, min(0.05, atr_pct * 1.5))
                    self.position_atr_activations[sig.symbol] = dynamic_activation
                    # [Idea 3] ATR 적응형 콜백: ATR×mult (0.8~3.0% 클램프) — 변동성 큰 종목일수록 넓게
                    cb_mult = float(getattr(self.cfg, 'TRAILING_ATR_CALLBACK_MULT', 1.3))
                    dynamic_callback = max(0.008, min(0.03, atr_pct * cb_mult))
                    self.position_atr_callbacks[sig.symbol] = dynamic_callback
                    logger.info(
                        f"[ATR TRAIL] {sig.symbol} ATR기반 저장: atr_pct={atr_pct*100:.2f}% → "
                        f"activation={dynamic_activation*100:.2f}% callback={dynamic_callback*100:.2f}%"
                    )
                else:
                    # ATR 정보 없으면 config 기본값 사용
                    self.position_atr_activations[sig.symbol] = getattr(self.cfg, 'TRAILING_ACTIVATE_PCT', 0.015)
                    self.position_atr_callbacks[sig.symbol] = getattr(self.cfg, 'TRAILING_CALLBACK_PCT', 0.012)
                
                # 활성 포지션 영구 상태 저장
                self.save_active_positions()
                try:
                    from core.engine import QuantumEngine
                    QuantumEngine.get_instance().save_engine_states()
                except Exception as persist_err:
                    logger.error(f"주문 완료 후 최근 진입 상태 저장 실패: {persist_err}")
                
                self.orders_today += 1
                stats_store.record_order()
                self._log_trade(sig, status="EXECUTED", result=result)
                logger.info(f"[ORDER] {sig.symbol} {sig.direction.upper()} 실행 완료")
                
                # [진입유실 근본수정] 역방향(BLUEFROG) 모드는 신호방향과 실제 체결방향이 반대다.
                
                #  신호방향을 기록하면 진입행은 LONG 버킷, 청산행(buy=숏청산)은 SHORT 버킷으로
                
                #  갈라져 페어링이 영구 실패하고, 대시보드가 진입시각/진입가를 역산해 만들어낸다.
                
                executed_side = str(result.get("side") or "").strip().lower()
                
                if executed_side not in ("long", "short", "buy", "sell"):
                
                    executed_side = sig.direction
                
                    logger.warning(f"[CSV LOG] {sig.symbol} 체결방향 확인 불가 → 신호방향({sig.direction})으로 기록")

                
                csv_log({
                    "timestamp": datetime.now(timezone(timedelta(hours=9))),
                    "symbol": sig.symbol,
                    "type": "진입",
                    "side": executed_side,
                    "price": result.get("entry_price", 0),
                    "amount": result.get("amount", 0),
                    "pnl_usdt": 0,
                    "pnl_pct": 0,
                    "trade_mode": getattr(self, "position_trade_modes", {}).get(sig.symbol if "sig" in locals() else symbol, "역방향" if getattr(CFG, "USE_BLUEFROG", True) else "순방향"),
                "exit_type": self.position_exit_profiles.get(sig.symbol, "SL/TP"),
                    "leverage": self.cfg.LEVERAGE,
                    "order_id": result.get("order_id", ""),
                })

                # [치명버그 수정] place_order가 sl_price/tp_price를 문자열로 돌려주는 경우가 있어

                #  :.6f 포맷이 TypeError로 터졌다. 이 예외는 scanner의 종목 루프 try에 잡혀

                #  경고 한 줄만 남기고 진입 후처리 전체를 중단시킨다.

                def _fmt_px(v):

                    try:

                        return f"{float(v):.6f}"

                    except (TypeError, ValueError):

                        return str(v if v not in (None, "") else "-")


                # 진입 성공 텔레그램 알림
                send_telegram_alert(
                    f"🟢 *[포지션 진입 완료]*\n"
                    f"종목: {sig.symbol}\n"
                    f"구분: {sig.direction.upper()} 진입\n"
                    f"진입가: {result.get('entry_price', 0)} USDT\n"
                    f"증거금: {margin_usdt:.2f} USDT\n"
                    f"레버리지: {self.cfg.LEVERAGE}x\n"
                    f"수량: {result.get('amount', 0)}\n"
                    f"익절 목표: {_fmt_px(result.get('tp_price', 0))}\n"
                    f"손절 설정: {_fmt_px(result.get('sl_price', 0))}"
                )
            else:
                self.pending_entry_locks.pop(sig.symbol, None)
                self._log_trade(sig, status="FAILED", reason="주문 API 오류")

    async def _risk_check(self, sig: Signal) -> tuple[bool, str]:
        now = datetime.now()

        # --- [WATCHDOG 1, 2, 3, 5] ---
        try:
            ticker = await self.client.get_ticker(sig.symbol)
            if ticker:
                ask = float(ticker.get('ask', 0))
                bid = float(ticker.get('bid', 0))
                last = float(ticker.get('last', 0))
                high24 = float(ticker.get('high', 0))
                low24 = float(ticker.get('low', 0))
                
                # W2. Spread
                if bid > 0 and ask > 0:
                    spread_pct = (ask - bid) / bid
                    if spread_pct > 0.01:
                        return False, f"진입 전 스프레드 과다 차단 (Spread: {spread_pct*100:.2f}% > 1%)"
                
                # W3. Volatility
                if high24 > 0 and low24 > 0:
                    volatility_24h = (high24 - low24) / low24
                    if volatility_24h > 0.15:
                        return False, f"극단적 변동성 서킷브레이커 발동 (24h 고저차: {volatility_24h*100:.1f}% > 15%)"
                        
                # W5. Fat-Finger
                # [2026-09-09] 종전에는 0.05가 코드에 박혀 있어 MAX_ENTRY_PRICE_DEV_PCT
                # 설정값(일봉봇 0.15)이 죽어 있었다. 일봉 전략은 '마지막 확정봉 종가'로
                # 신호를 내므로 현재가와의 이격에 하루치 변동이 통째로 들어간다.
                # DOT 실측: 09-07 종가 1.0621 vs 현재가 1.2476 → 이격 15% → 진입 100% 차단.
                _dev_cap = float(getattr(self.cfg, "MAX_ENTRY_PRICE_DEV_PCT", 0.05))
                if last > 0 and sig.close > 0:
                    price_diff = abs(last - sig.close) / last
                    if price_diff > _dev_cap:
                        return False, (f"이상 가격 차단 (시세 {last} vs 시그널 {sig.close}, "
                                       f"이격 {price_diff*100:.1f}% > {_dev_cap*100:.0f}%)")
                # W13. Meta-Labeling Filter (24h Microstructure)
                if getattr(self.cfg, "USE_META_LABELING", True) and high24 > 0 and low24 > 0 and high24 > low24:
                    pos_24h = (last - low24) / (high24 - low24)
                    if getattr(self.cfg, "META_REJECT_EXTREMES", True):
                        if sig.direction == "long" and pos_24h > 0.95:
                            return False, f"메타 라벨링 차단 (False Positive): 24h 최고점 반경 5% 내 추격 롱 진입 금지 (pos_24h: {pos_24h*100:.1f}%)"
                        if sig.direction == "short" and pos_24h < 0.05:
                            return False, f"메타 라벨링 차단 (False Positive): 24h 최저점 반경 5% 내 추격 숏 진입 금지 (pos_24h: {pos_24h*100:.1f}%)"

        except Exception as e:
            logger.warning(f"[WATCHDOG] Ticker 체크 예외: {e}")

        # W1. Ping-pong
        if not hasattr(self, "_entry_timestamps"):
            self._entry_timestamps = {}
        ts_list = self._entry_timestamps.get(sig.symbol, [])
        ts_list = [t for t in ts_list if (now - t).total_seconds() < 180]
        if len(ts_list) >= 3:
            return False, f"주문 빈도 폭주 차단 (3분 내 3회 이상 시그널 발생)"
        ts_list.append(now)
        self._entry_timestamps[sig.symbol] = ts_list
        # -----------------------------

        if self.global_cooldown_until and now < self.global_cooldown_until:
            remaining = (self.global_cooldown_until - now).total_seconds()
            return False, f"글로벌 쿨다운 진행 중 (남은 시간: {remaining:.1f}초)"

        if sig.symbol in self.symbol_cooldown_until:
            until = self.symbol_cooldown_until[sig.symbol]
            if now < until:
                # [v9.8.0] 동적 격리 해제 조건 검사: ADX < 20.0 및 200 EMA 안착 시 조기 해제 허용
                if getattr(self.cfg, "USE_DYNAMIC_QUARANTINE", True) and getattr(sig, "adx", 0.0) > 0 and sig.adx < 20.0:
                    dist_ema = abs(sig.close - getattr(sig, "ema200", sig.close)) / getattr(sig, "ema200", sig.close)
                    if dist_ema < 0.012:
                        logger.info(f"[QUARANTINE RELEASE] {sig.symbol} ADX({sig.adx:.1f} < 20.0) 안정화 및 EMA200 복귀로 동적 격리 조기 해제!")
                        self.symbol_cooldown_until.pop(sig.symbol, None)
                    else:
                        remaining = (until - now).total_seconds()
                        return False, f"{sig.symbol} 종목별 동적 격리 중 (ADX={sig.adx:.1f}, 이격={dist_ema*100:.1f}%, 남은시간 {remaining:.1f}초)"
                else:
                    remaining = (until - now).total_seconds()
                    return False, f"{sig.symbol} 종목별 쿨다운/격리 진행 중 (남은 시간: {remaining:.1f}초)"
            else:
                self.symbol_cooldown_until.pop(sig.symbol, None)

        if getattr(self, "_halted_by_consec_sl", False):
            return False, (f"당일 연속손절 정지: {self._daily_consec_sl}연속 손절 "
                           f"(한도 {int(getattr(self.cfg, 'MAX_CONSEC_SL_PER_DAY', 0))}회, 다음날 재개)")

        if self.daily_pnl_usdt <= -self.cfg.DAILY_LOSS_LIMIT_USDT:
            if not getattr(self, "_daily_loss_alert_sent", False):
                self._daily_loss_alert_sent = True
                send_telegram_alert(
                    f"🚨 *[RISK ALERT]* 일일 손실 한도 초과! 자동매매 신규 진입이 차단됩니다.\n"
                    f"금일 누적 손익: {self.daily_pnl_usdt:.2f} USDT (한도: {self.cfg.DAILY_LOSS_LIMIT_USDT} USDT)"
                )
            return False, f"일일 손실 한도 초과: {self.daily_pnl_usdt:.2f} USDT"

        # [v8.5.0] 일일 익절 목표 달성 시 신규 진입 차단 (config에만 있고 미구현이던 기능)
        profit_limit = float(getattr(self.cfg, "DAILY_PROFIT_LIMIT_USDT", 0.0) or 0.0)
        if profit_limit > 0 and self.daily_pnl_usdt >= profit_limit:
            if not getattr(self, "_daily_profit_alert_sent", False):
                self._daily_profit_alert_sent = True
                send_telegram_alert(
                    f"🎯 *[일일 익절 목표 달성]* 금일 누적 손익 {self.daily_pnl_usdt:.2f} USDT "
                    f"(목표 {profit_limit} USDT) → 신규 진입을 중단합니다. 다음날 자동 재개됩니다."
                )
            return False, f"일일 익절 목표 달성: {self.daily_pnl_usdt:.2f} USDT (목표 {profit_limit} USDT)"

        balance = await self.client.get_balance()
        self._last_risk_balance = balance
        total = balance.get("total", 0)
        if total < self.cfg.MIN_REQUIRED_BALANCE_USDT:
            return False, f"잔고 부족 (< {self.cfg.MIN_REQUIRED_BALANCE_USDT} USDT)"

        try:
            _stats = stats_store.load_stats()
            seed_money = _stats.get("seed_money", 0)
            if seed_money > 0:
                drawdown_pct = (seed_money - total) / seed_money
                if drawdown_pct >= self.cfg.MAX_DRAWDOWN_PCT:
                    return False, f"최대 낙폭 초과: {drawdown_pct*100:.1f}%"
        except Exception as e:
            logger.warning(f"[RISK] MDD 체크 중 예외: {e}")

        # W/M 전략 최대 강도=95, MR=90, 구 Breakout=100
        # [8405 복제] DualBB 신호 강도=100(RSI확정)/85(RSI미확정) → 게이트 80
        if sig.strategy_type in ("DoubleBottom", "DoubleTop"):
            required_strength = 80
        elif sig.strategy_type == "Mean Reversion":
            required_strength = 80
        elif sig.strategy_type == "QAR-ARE":
            # [2026-08-26] QAR-ARE 신호 강도 게이트 (60% 이상 통과)
            required_strength = 60
        elif sig.strategy_type == "DualBB":
            required_strength = 80
        elif getattr(sig, "strategy_type", "") == "BBTS":
            required_strength = 80
        elif sig.strategy_type == "MACross":
            # [2026-08-25] MA 교차는 교차 발생 자체가 신호다. 강도는 두 선이 벌어진
            # 폭을 표시할 뿐이라 문턱을 두면 검증 조건과 어긋난다. 8408과 동일하게 0.
            required_strength = 0
        elif sig.strategy_type == "Sniper15":
            # [2026-08-19] '15분봉 세력 흔적' 기법은 신호 수식 5조건 + 두 라인 돌파를
            # 모두 만족해야만 신호가 나온다. 그 자체가 필터라 별도 강도 기준을 두면
            # 문서 원칙(조건 충족 시 즉시 매수)과 어긋난다.
            required_strength = 0
        else:
            required_strength = 90
        if sig.strength < required_strength:
            return False, f"신호 강도 부족: {sig.strength}% (필요 강도: {required_strength}%)"

        free = balance.get("free", 0)
        # [v2.15.0] 가용 증거금 평가 기준 정렬 (Compounding Margin alignment)
        if getattr(self.cfg, "USE_AUTO_COMPOUND", False):
            compound_pct = float(getattr(self.cfg, "AUTO_COMPOUND_PCT", 18.0))
            required_margin = round(total * (compound_pct / 100.0), 2)
        else:
            required_margin = self.cfg.MARGIN_USDT * getattr(self.cfg, 'EQUITY_SCALE_FACTOR', 1.0)

        # [M4] 합산 리스크 검사
        max_total_risk_pct = float(getattr(self.cfg, "MAX_TOTAL_RISK_PCT", 0.22))
        if max_total_risk_pct > 0 and total > 0:
            try:
                positions = await self.client.get_positions()
                total_risk_usdt = 0.0
                for p in positions:
                    sym = p["symbol"]
                    notional = float(p.get("notionalUsd", p.get("notional", 0.0)))
                    if notional == 0.0:
                        sz = float(p.get("size", 0.0))
                        ep = float(p.get("entry_price", 0.0))
                        contract_size = float(self.client._markets.get(sym, {}).get("contractSize", 1.0) or 1.0)
                        notional = sz * ep * contract_size
                    
                    sp = self.pos_manager.stop_prices.get(sym)
                    ep = float(p.get("entry_price", 1.0))
                    if sp is not None and sp > 0 and ep > 0:
                        sl_dist = abs(ep - sp) / ep
                    else:
                        sl_dist = float(getattr(self.cfg, "STOP_LOSS_PCT", 0.02))
                    
                    total_risk_usdt += notional * sl_dist
                    
                if total_risk_usdt > total * max_total_risk_pct:
                    return False, f"합산 리스크({total_risk_usdt:.2f} USDT)가 한도({total*max_total_risk_pct:.2f} USDT) 초과"
            except Exception as e:
                logger.warning(f"[RISK] 합산 리스크 평가 중 예외: {e}")

        if free < required_margin:
            return False, f"가용 증거금 부족: {free:.2f} < {required_margin:.2f} (복리 계산 기준)"

        return True, "OK"

    def _reset_daily_if_needed(self):
        today = (datetime.utcnow() + timedelta(hours=9)).date()
        if today != self._today:
            self.daily_pnl_usdt = 0.0
            self.orders_today = 0
            self._daily_loss_alert_sent = False
            self._daily_profit_alert_sent = False
            self._today = today
            # [당일 연속손절 정지] 날짜 변경 → 카운터·정지 해제 후 자동 재개
            self._daily_consec_sl = 0
            self._consec_sl_date = today
            if getattr(self, "_halted_by_consec_sl", False):
                self._halted_by_consec_sl = False
                self.enable()
                logger.info("[연속손절 정지] 날짜 변경 → 자동매매 재개")
            elif getattr(self.cfg, "AUTO_TRADING", True) and not self.enabled:
                self.enable()
                logger.info("[일일 리셋] 날짜 변경 및 AUTO_TRADING 확인 → 자동매매 재개")
            _s = stats_store.load_stats()
            _s["orders_today"] = 0
            _s["daily_pnl_usdt"] = 0.0
            # [2026-09-11] 위에서 **메모리의** 연속손절 정지를 풀면서 디스크에는 쓰지 않아
            # stats.json에 halted_by_consec_sl=True가 그대로 남았다.
            # 대시보드(8888 app.py)는 이 파일을 읽어 쿨다운을 판정하므로,
            # 봇은 정상 매매하는데 화면만 쿨다운으로 표시된다(8409 실측 2026-09-11:
            # halted=True·consec_sl_date=09-10인데 09-11 진입 3건 정상 발생).
            # save_cooldowns()가 다음 청산에서 덮어쓸 때까지 어긋난 채로 남는다.
            _s["daily_consec_sl"] = 0
            _s["consec_sl_date"] = today.isoformat()
            _s["halted_by_consec_sl"] = False
            stats_store.save_stats(_s)

    def _log_trade(self, sig: Signal, status: str, reason: str = "", result: Optional[Dict] = None):
        # [Reverse Trading] Log actual executed direction
        actual_dir = sig.direction
        if result and "side" in result:
            actual_dir = "long" if result["side"] == "buy" else "short"
        entry = {
            "timestamp": datetime.utcnow() + timedelta(hours=9),
            "symbol": sig.symbol,
            "direction": actual_dir,
            "strength": sig.strength,
            "status": status,
            "reason": reason,
            "entry_price": result.get("entry_price", 0) if result else 0,
            "sl_price": result.get("sl_price", 0) if result else 0,
            "tp_price": result.get("tp_price", 0) if result else 0,
        }
        self.trade_log.append(entry)
        if len(self.trade_log) > 500:
            self.trade_log = self.trade_log[-500:]

    async def get_trade_log(self) -> List[Dict]:
        async with self.lock:
            return list(reversed(self.trade_log))
