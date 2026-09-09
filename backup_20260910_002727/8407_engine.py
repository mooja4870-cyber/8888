"""
AI QUANTUM — Orchestration Engine (v2 Async Enterprise)
모든 모듈을 통합 관리하는 중앙 컨트롤러. 비동기 이벤트 루프를 백그라운드 스레드에서 구동하여 UI 블로킹 방지.
"""
import os
import logging
import threading
import asyncio
import time
import inspect
import concurrent.futures
from enum import Enum, auto
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta

from core.exchange import BinanceClient
from core.scanner import Scanner
from core.trader import AutoTrader
from core.config import CFG
import core.stats as stats_store
from core.logger import log_trade as csv_log
from core.trailing_stop_manager import TrailingStopManager
from core.trade_lock import holder_pid as trade_lock_holder_pid
from core.pnl_reconciler import PnLReconciler
from core.history_helper import (
    compact_local_trade_history,
    get_position_direction,
    load_local_trade_history,
    _normalize_id,
    _trade_dedupe_key,
)
from core.alert import send_telegram_alert

logger = logging.getLogger(__name__)


def _epoch_ms(value) -> float:
    """체결 타임스탬프를 epoch 밀리초(float)로 정규화한다.

    exchange.get_trade_history()는 timestamp를 **pandas.Timestamp**로 담아 준다.
    여기에 float()을 직접 걸면 TypeError가 나고, 그 예외가 청산 기록 블록 전체를
    삼켜 **청산이 CSV에 한 건도 남지 않는다.**
    [2026-08-27] 8401 v10.1.0에서 확인한 버그를 전 봇에 이식.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    ts = getattr(value, "timestamp", None)
    if callable(ts):
        try:
            return float(ts()) * 1000.0
        except Exception:
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

class EngineState(Enum):
    IDLE = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    SCANNING = auto()
    TRADING = auto()
    ERROR = auto()
    RECOVERING = auto()

_TRANSITIONS = {
    EngineState.IDLE:       {EngineState.CONNECTING},
    EngineState.CONNECTING: {EngineState.CONNECTED, EngineState.ERROR},
    EngineState.CONNECTED:  {EngineState.SCANNING, EngineState.IDLE, EngineState.CONNECTING, EngineState.ERROR},
    EngineState.SCANNING:   {EngineState.TRADING, EngineState.CONNECTED, EngineState.ERROR, EngineState.CONNECTING},
    EngineState.TRADING:    {EngineState.SCANNING, EngineState.CONNECTED, EngineState.ERROR, EngineState.CONNECTING},
    EngineState.ERROR:      {EngineState.RECOVERING, EngineState.IDLE, EngineState.CONNECTING},
    EngineState.RECOVERING: {EngineState.CONNECTED, EngineState.ERROR, EngineState.IDLE, EngineState.CONNECTING},
}

class QuantumEngine:
    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.client: Optional[BinanceClient] = None
        self.scanner: Optional[Scanner] = None
        self.trader: Optional[AutoTrader] = None
        self.cfg = CFG

        self._initialized = False
        self._prev_position_symbols: set = set()
        self._ts_triggered: set = set()
        self._trailing_highs: Dict[str, float] = {}
        self._trailing_lows: Dict[str, float] = {}
        self._timeout_cooldowns: Dict[str, float] = {}
        self._timeout_failure_counts: Dict[str, int] = {}  # [v2.15.0] 강제청산 연속 실패 횟수 추적
        self.closing_symbols: Dict[str, float] = {}  # [v2.15.0] 브라우저 세션 대신 engine에 보존되는 청산 중 캐시
        # [v2.8.0] per-symbol 청산 중 락: 이중 클릭 및 스캔 루프와 충돌 방지
        self._closing_in_progress: Dict[str, float] = {}  # symbol -> 청산 시작 timestamp
        # 대시보드 API 캐싱 변수
        self._cached_balance = None
        self._cached_positions = None
        # [v3.1.68] 포지션 캐시 TTL: 자동(SL/TP/ATR)청산 종목이 묵은 캐시로 잔상처럼 남는 것 방지
        self._cached_positions_ts = 0.0
        self._DASH_CACHE_TTL = 8.0  # 초. 이보다 오래된 캐시는 대시보드 요청 시 거래소에서 재조회
        # [B] 포지션 사라짐 즉시 감지용: 직전 보유 심볼 집합
        self._last_pos_syms = set()

        self._state = EngineState.IDLE
        self._state_lock = threading.Lock()
        self._error_msg = ""
        self._recovery_attempts = 0
        self._max_recovery_attempts = 3

        self._api_key = ""
        self._secret_key = ""
        self._passphrase = ""

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._start_loop, daemon=True)
        self._loop_thread.start()
        
        self._async_lock = None 
        self.pnl_reconciler = PnLReconciler(self)
        self.trailing_stop_manager = TrailingStopManager(self)

    def _start_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _entry_trade_mode(self, symbol: str) -> str:
        """[v9.9.3] 청산 로그의 매매모드는 '진입 시점' 값이어야 한다.
        기존엔 청산하는 순간의 CFG.USE_BLUEFROG를 찍어, 스위칭이 끼면 같은 거래의
        진입행(순방향)과 청산행(역방향)이 어긋나 스위칭 이력이 은폐됐다.
        진입 시 보존한 값을 우선 쓰고, 없을 때만 현재값으로 폴백한다."""
        if self.trader:
            mode = getattr(self.trader, "position_trade_modes", {}).get(symbol)
            if mode:
                return mode
        return "역방향" if getattr(self.cfg, "USE_BLUEFROG", True) else "순방향"

    def _infer_exit_type(self, symbol: str, is_ts: bool, local_trades: Optional[List[Dict]] = None) -> str:
        if is_ts:
            return "T/S"
        if self.trader:
            profile = getattr(self.trader, "position_exit_profiles", {}).get(symbol)
            if profile in ("ATR", "SL/TP"):
                return profile
        lookup = local_trades if local_trades is not None else load_local_trade_history()
        for t in reversed(lookup):
            if t.get("symbol") != symbol:
                continue
            if t.get("category") not in ("진입", "*진입"):
                continue
            et = str(t.get("exit_type", "")).strip()
            if et in ("ATR", "SL/TP"):
                return et
        return "SL/TP"

    def save_engine_states(self):
        try:
            import os
            import json
            os.makedirs("data", exist_ok=True)
            data = {
                "trailing_highs": self._trailing_highs,
                "trailing_lows": self._trailing_lows,
                "prev_position_symbols": list(self._prev_position_symbols),
                "recently_entered": {
                    sym: dt.isoformat() for sym, dt in self.trader.recently_entered.items()
                } if self.trader else {}
            }
            tmp = "data/engine_states.json.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, "data/engine_states.json")
            logger.info("[PERSIST] 엔진 상태(트레일링 픽, 이전 포지션 심볼, recently_entered) 저장 완료")
        except Exception as e:
            logger.error(f"[PERSIST ERROR] 엔진 상태 저장 실패: {e}")

    def load_engine_states(self):
        try:
            import os
            import json
            if os.path.exists("data/engine_states.json"):
                with open("data/engine_states.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._trailing_highs = data.get("trailing_highs", {})
                self._trailing_lows = data.get("trailing_lows", {})
                self._prev_position_symbols = set(data.get("prev_position_symbols", []))
                if self.trader:
                    # 재시작 시 트레일링 상태와 활성 포지션 메타데이터 정합성 보정
                    valid_syms = set(getattr(self.trader, "position_strategies", {}).keys())
                    if valid_syms:
                        self._trailing_highs = {k: v for k, v in self._trailing_highs.items() if k in valid_syms}
                        self._trailing_lows = {k: v for k, v in self._trailing_lows.items() if k in valid_syms}
                    rec_ent = data.get("recently_entered", {})
                    for sym, dt_str in rec_ent.items():
                        try:
                            self.trader.recently_entered[sym] = datetime.fromisoformat(dt_str)
                        except Exception:
                            pass
                logger.info("[PERSIST] 엔진 상태(트레일링 픽, 이전 포지션 심볼, recently_entered) 복구 완료")
        except Exception as e:
            logger.error(f"[PERSIST ERROR] 엔진 상태 복구 실패: {e}")


    # --- Sync Wrappers for Streamlit UI ---

    def initialize(self, api_key: str, secret_key: str, passphrase: str) -> tuple[bool, str]:
        future = asyncio.run_coroutine_threadsafe(self._initialize_async(api_key, secret_key, passphrase), self._loop)
        return future.result()

    def start_scanner(self):
        asyncio.run_coroutine_threadsafe(self._start_scanner_async(), self._loop)

    def stop_scanner(self):
        future = asyncio.run_coroutine_threadsafe(self._stop_scanner_async(), self._loop)
        future.result()

    def enable_trading(self):
        future = asyncio.run_coroutine_threadsafe(self._enable_trading_async(), self._loop)
        future.result()

    def disable_trading(self):
        future = asyncio.run_coroutine_threadsafe(self._disable_trading_async(), self._loop)
        future.result()

    def attempt_recovery(self) -> tuple[bool, str]:
        future = asyncio.run_coroutine_threadsafe(self._attempt_recovery_async(), self._loop)
        return future.result()

    def get_dashboard_data(self) -> Dict:
        # [perf] 짧은 TTL 캐시 + 타임아웃 + 실패 시 직전값 폴백
        #  - 잦은 리런마다 OKX 동기 재호출로 인한 로딩지연 방지
        #  - 응답 무한 대기로 UI가 멈추는 것 방지(8초 타임아웃)
        now = time.time()
        cached = getattr(self, "_dash_cache", None)
        ttl = float(getattr(self.cfg, "DASHBOARD_CACHE_TTL_SEC", 2.5))
        if cached and (now - cached[0]) < ttl:
            return cached[1]
        try:
            future = asyncio.run_coroutine_threadsafe(self._get_dashboard_data_async(), self._loop)
            data = future.result(timeout=1.5)
            self._dash_cache = (now, data)
            return data
        except Exception as e:
            logger.warning(f"[DASH] get_dashboard_data 지연/실패({e}) — 직전 캐시/빈값 반환")
            return cached[1] if cached else {}

    def get_scanner_logs(self, last_n: int = 50) -> list[str]:
        if not self.scanner:
            return ["[SYS] 엔진 미연결"]
        try:
            future = asyncio.run_coroutine_threadsafe(self.scanner.get_logs(last_n), self._loop)
            return future.result(timeout=1.0)  # [perf] 렌더 무한 블로킹 방지
        except Exception:
            return ["[SYS] 로그 조회 지연/타임아웃"]

    def clear_scanner_cache(self) -> None:
        if self.scanner:
            future = asyncio.run_coroutine_threadsafe(self.scanner.clear_cache(), self._loop)
            future.result()

    async def close_position_async(self, symbol: str, side: str) -> bool:
        """
        [v2.16.0] 비동기 포지션 청산 래퍼 — 트레일링 스탑, 타임아웃, 로테이션 등 내부 비동기 루프에서 직접 호출
        """
        if not self.is_ready:
            return False

        now_sec = time.time()
        last_close = self._closing_in_progress.get(symbol, 0.0)
        if (now_sec - last_close) < 10.0:
            logger.warning(f"[CLOSE GUARD] {symbol} 청산 진행 중 (이중 요청 차단, 남은: {10.0 - (now_sec - last_close):.1f}초)")
            return False
        self._closing_in_progress[symbol] = now_sec

        try:
            res = await self._maybe_await(self.client.close_position(symbol, side))
            if res:
                self._trailing_highs.pop(symbol, None)
                self._trailing_lows.pop(symbol, None)
                self._timeout_cooldowns.pop(symbol, None)
                self._timeout_failure_counts.pop(symbol, None)
                self._cached_positions = None
                self._cached_balance = None
                if self.trader:
                    self.trader.position_strategies.pop(symbol, None)
                    if hasattr(self.trader, 'position_atr_activations'):
                        self.trader.position_atr_activations.pop(symbol, None)
                    self.trader.save_active_positions()
                self.save_engine_states()
            self._closing_in_progress.pop(symbol, None)
            return res
        except Exception as e:
            logger.error(f"[CLOSE ERROR] {symbol} 청산 중 예외: {e}")
            self._closing_in_progress.pop(symbol, None)
            return False

    def close_position(self, symbol: str, side: str) -> bool:
        if not self.is_ready:
            return False
        future = asyncio.run_coroutine_threadsafe(self.close_position_async(symbol, side), self._loop)
        try:
            return future.result(timeout=16)
        except concurrent.futures.TimeoutError:
            logger.error(f"[CLOSE TIMEOUT] {symbol} 청산 API 응답 없음 (16초 초과) — 청산 실패 처리")
            return False
        except Exception as e:
            logger.error(f"[CLOSE ERROR] {symbol} 청산 중 예외: {e}")
            return False

    def close_all_positions(self) -> int:
        """
        [v2.8.0] 일괄청산 래퍼
        - exchange.close_all_positions가 asyncio.gather 병렬화되어 실제 N개 포지션도 ~18초 내 완료
        - timeout: 45초 (병렬 처리로 30초도 충분하지만 API 스파이크 대비 15초 여유)
        - timeout 발생 시 -1 반환: 부분 청산 가능성 시그널 (UI에서 ⚠️ 쯔피션 비교 권고)
        """
        if not self.is_ready:
            return 0
        future = asyncio.run_coroutine_threadsafe(self.client.close_all_positions(), self._loop)
        try:
            count = future.result(timeout=45)  # [v2.8.0] 30초 → 45초 (병렬화후 여유부 확장)
            if count > 0 or count == -1:
                self._trailing_highs.clear()
                self._trailing_lows.clear()
                self._timeout_cooldowns.clear()
                self._closing_in_progress.clear()  # [v2.8.0] 모든 락 해제
                # 캐시 즉시 무효화
                self._cached_positions = None
                self._cached_balance = None
                self.save_engine_states()
            return count
        except concurrent.futures.TimeoutError:
            logger.error("[CLOSE ALL TIMEOUT] 일괄청산 API 응답 없음 (45초 초과) — 부분 청산 가능성 있음")
            self._closing_in_progress.clear()  # [v2.8.0] 타임아웃시도 락 해제
            return -1  # [v2.8.0] 0 → -1: 부분 청산 시그널
        except Exception as e:
            logger.error(f"[CLOSE ALL ERROR] 일괄청산 중 예외: {e}")
            self._closing_in_progress.clear()  # [v2.8.0] 예외시도 락 해제
            return 0

    def get_scan_results(self) -> List[Dict]:
        if not self.scanner: return []
        future = asyncio.run_coroutine_threadsafe(self.scanner.get_results(), self._loop)
        return future.result()

    def get_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 80):
        """UI에서 hover 미니 차트를 그릴 때 쓰는 안전한 동기 OHLCV 조회 래퍼."""
        if not self.is_ready or not self.client:
            return None
        future = asyncio.run_coroutine_threadsafe(
            self.client.get_ohlcv(symbol, timeframe=timeframe, limit=limit),
            self._loop,
        )
        try:
            return future.result(timeout=8)
        except concurrent.futures.TimeoutError:
            logger.warning(f"[OHLCV TIMEOUT] {symbol} {timeframe} {limit}개 캔들 조회 지연")
            return None
        except Exception as e:
            logger.warning(f"[OHLCV ERROR] {symbol} hover 차트 조회 실패: {e}")
            return None

    def get_system_logs(self, limit: int = 50) -> List[str]:
        if not self.scanner: return []
        future = asyncio.run_coroutine_threadsafe(self.scanner.get_logs(limit), self._loop)
        return future.result()

    def get_trader_logs(self) -> List[Dict]:
        if not self.trader: return []
        future = asyncio.run_coroutine_threadsafe(self.trader.get_trade_log(), self._loop)
        return future.result()

    def get_trade_history(self, symbol: Optional[str] = None, limit: int = 50) -> List[Dict]:
        if not self.client: return []
        future = asyncio.run_coroutine_threadsafe(self.client.get_trade_history(symbol, limit), self._loop)
        return future.result()

    def sync_trades_to_csv(self) -> int:
        if not self.is_ready:
            return 0
        future = asyncio.run_coroutine_threadsafe(self.pnl_reconciler.sync_trades_async(), self._loop)
        return future.result()

    def _check_closed_positions(self):
        if not self.is_ready:
            return
        future = asyncio.run_coroutine_threadsafe(self._check_closed_positions_async(), self._loop)
        return future.result()

    def get_health(self) -> Dict:
        return {
            "engine_state": self._state.name,
            "api_connected": self.is_ready,
            "scanner_running": self.scanner.is_running if self.scanner else False,
            "trading_enabled": self.trader.enabled if self.trader else False,
            "recovery_attempts": self._recovery_attempts,
            "last_error": self._error_msg,
            "scan_count": self.scanner.scan_count if self.scanner else 0,
        }

    @property
    def state(self) -> EngineState:
        return self._state
        
    @property
    def is_ready(self) -> bool:
        return self._initialized and self.client is not None

    def _transition(self, new_state: EngineState, reason: str = ""):
        with self._state_lock:
            allowed = _TRANSITIONS.get(self._state, set())
            if new_state not in allowed:
                logger.warning(f"[FSM] 유효하지 않은 전이: {self._state.name} → {new_state.name}")
                return False
            old = self._state
            self._state = new_state
            logger.info(f"[FSM] {old.name} → {new_state.name} | {reason}")
            
            # 텔레그램 메시지 알림 (핵심 상태 전이 대상)
            if new_state == EngineState.ERROR:
                send_telegram_alert(f"🚨 *[AI QUANTUM] 엔진 에러 상태 전이*\n이전 상태: {old.name}\n사유: {reason or self._error_msg}")
            elif new_state == EngineState.CONNECTED and old == EngineState.RECOVERING:
                send_telegram_alert(f"✅ *[AI QUANTUM] 엔진 자가 복구 성공*\n시도 횟수: {self._recovery_attempts}회")
            
            return True

    # --- Async Implementations ---

    async def _initialize_async(self, api_key: str, secret_key: str, passphrase: str) -> tuple[bool, str]:
        if self._initialized and self._state != EngineState.ERROR and self._api_key == api_key and self._secret_key == secret_key:
            return True, "✅ 엔진이 이미 활성화되어 있습니다."

        self._transition(EngineState.CONNECTING, "API 연결 시도")
        self._api_key = api_key
        self._secret_key = secret_key
        self._passphrase = passphrase

        if self._async_lock is None:
            self._async_lock = asyncio.Lock()

        async with self._async_lock:
            try:
                self.client = BinanceClient(api_key, secret_key, passphrase)
                if await self.client.load_markets():
                    self.scanner = Scanner(self.client)
                    self.trader = AutoTrader(self.client)
                    self.load_engine_states()

                    self.scanner.on_signal = self.trader.on_signal
                    self.scanner.on_scan_complete = self._check_closed_positions_async
                    self.scanner.on_gap_exit = self._handle_gap_exit_async

                    self._initialized = True
                    self._recovery_attempts = 0
                    self._transition(EngineState.CONNECTED, "마켓 로드 성공")
                    
                    # 초기 캐시 로드
                    try:
                        self._cached_balance = await self.client.get_balance()
                        self._cached_positions = await self.client.get_positions()
                        self._cached_positions_ts = time.time()  # [v3.1.68] 신선도 갱신
                        if self.trader:
                            self.trader.sync_active_positions(self._cached_positions)
                    except Exception as ce:
                        logger.warning(f"초기 대시보드 데이터 캐싱 및 동기화 실패: {ce}")

                    # 당일 누적 PnL 동기화 및 복구 실행 (PnL Reconciler)
                    async def _bg_reconcile():
                        try:
                            await self.pnl_reconciler.sync_trades_async()
                            await self.pnl_reconciler.reconcile_daily_pnl_async()
                        except Exception as re:
                            logger.error(f"초기 PnL Reconcile 실패: {re}")
                    asyncio.create_task(_bg_reconcile())
                    
                    send_telegram_alert("🤖 *[AI QUANTUM]* Binance 자동매매 엔진 초기화 및 가동 성공")
                    asyncio.create_task(self._health_check_loop())
                    return True, "✅ 엔진 초기화 및 마켓 로드 성공"

                self._error_msg = "마켓 정보 로드 실패"
                self._transition(EngineState.ERROR, self._error_msg)
                return False, f"❌ {self._error_msg}"
            except Exception as e:
                self._error_msg = str(e)
                logger.error(f"엔진 초기화 실패: {e}")
                self._transition(EngineState.ERROR, f"초기화 예외: {e}")
                return False, f"❌ 엔진 초기화 오류: {e}"

    async def _start_scanner_async(self):
        if self.scanner and not self.scanner.is_running:
            self.scanner.start()
            self._transition(EngineState.SCANNING, "스캐너 시작")

    async def _stop_scanner_async(self):
        if self.scanner:
            await self.scanner.stop()
            if self._state == EngineState.TRADING:
                await self._disable_trading_async()
            if self.is_ready:
                self._transition(EngineState.CONNECTED, "스캐너 중지")

    async def _enable_trading_async(self):
        if self.trader:
            self.trader.enable()
            if self._state == EngineState.SCANNING:
                self._transition(EngineState.TRADING, "자동매매 활성화")

    async def _disable_trading_async(self):
        if self.trader:
            self.trader.disable()
            if self._state == EngineState.TRADING:
                self._transition(EngineState.SCANNING, "자동매매 비활성화")

    async def _attempt_recovery_async(self) -> tuple[bool, str]:
        if self._state != EngineState.ERROR:
            return False, "ERROR 상태가 아님"

        if self._recovery_attempts >= self._max_recovery_attempts:
            return False, f"최대 복구 횟수 초과 ({self._max_recovery_attempts}회)"

        self._transition(EngineState.RECOVERING, f"복구 시도 #{self._recovery_attempts + 1}")
        self._recovery_attempts += 1

        wait = min(2 ** self._recovery_attempts, 30)
        logger.info(f"[RECOVERY] {wait}초 대기 후 재연결...")
        await asyncio.sleep(wait)

        if self._api_key:
            success, msg = await self._initialize_async(self._api_key, self._secret_key, self._passphrase)
            if success:
                return True, f"✅ 복구 성공 (시도 #{self._recovery_attempts})"

        self._transition(EngineState.ERROR, "복구 실패")
        return False, f"❌ 복구 실패 (시도 #{self._recovery_attempts})"

    async def _get_dashboard_data_async(self) -> Dict:
        if not self.is_ready:
            return {}

        try:
            # [v3.1.68] TTL 초과 시 강제 재조회 → 자동청산 종목 잔상 방지
            stale = (time.time() - self._cached_positions_ts) > self._DASH_CACHE_TTL
            if self._cached_balance is None or stale:
                self._cached_balance = await self.client.get_balance()
            if self._cached_positions is None or stale:
                self._cached_positions = await self.client.get_positions()
                self._cached_positions_ts = time.time()
                # [B] 포지션 사라짐 즉시 감지 → 청산 기록 트리거 (스캔 완료를 기다리지 않음)
                try:
                    cur_syms = {p.get("symbol") for p in (self._cached_positions or [])
                                if abs(float(p.get("size", 0) or 0)) > 0}
                    vanished = self._last_pos_syms - cur_syms
                    self._last_pos_syms = cur_syms
                    if vanished:
                        logger.info(f"[B 즉시기록] 포지션 사라짐 감지 {vanished} → 청산 기록 즉시 실행")
                        await self._check_closed_positions_async()
                except Exception as _be:
                    logger.warning(f"[B 즉시기록] 트리거 오류: {_be}")
        except Exception as e:
            # [v4.4.1 네트워크 완충] 10개 봇 동시 가동 시 순간 타임아웃/DNS 지연은 정상 범주.
            # 캐시가 있으면 직전 데이터로 응답(degraded 표시)하고, 3연속 실패부터 ERROR 전환.
            self._dash_fail_streak = getattr(self, "_dash_fail_streak", 0) + 1
            logger.warning(f"대시보드 데이터 조회 실패({self._dash_fail_streak}연속): {e}")
            self._error_msg = str(e)
            if self._dash_fail_streak >= 3:
                if self._state not in (EngineState.ERROR, EngineState.RECOVERING):
                    self._transition(EngineState.ERROR, f"데이터 조회 실패: {e}")
            if self._cached_balance is None and self._cached_positions is None:
                return {}
            return {
                "total_balance": self._cached_balance.get("total", 0) if self._cached_balance else 0.0,
                "free_margin": max(0.0, (self._cached_balance.get("total", 0) if self._cached_balance else 0.0) - sum(p.get("amount_usdt", 0) for p in (self._cached_positions or []))) if self._cached_positions else (self._cached_balance.get("free", 0) if self._cached_balance else 0.0),
                "used_margin": sum(p.get("amount_usdt", 0) for p in (self._cached_positions or [])) if self._cached_positions else (self._cached_balance.get("used", 0) if self._cached_balance else 0.0),
                "realized_pnl": self._cached_balance.get("pnl", 0) if self._cached_balance else 0.0,
                "positions": self._cached_positions or [],
                "is_scanning": self.scanner.is_running if self.scanner else False,
                "is_trading": self.trader.enabled if self.trader else False,
                "engine_state": self._state.name,
                "degraded": True,
                "data_age_sec": int(time.time() - (self._cached_positions_ts or 0)),
            }
        self._dash_fail_streak = 0  # 성공 시 연속실패 카운터 초기화
        self._error_msg = ""

        return {
            "total_balance": self._cached_balance.get("total", 0) if self._cached_balance else 0.0,
            "free_margin": max(0.0, (self._cached_balance.get("total", 0) if self._cached_balance else 0.0) - sum(p.get("amount_usdt", 0) for p in (self._cached_positions or []))) if self._cached_positions else (self._cached_balance.get("free", 0) if self._cached_balance else 0.0),
            "used_margin": sum(p.get("amount_usdt", 0) for p in (self._cached_positions or [])) if self._cached_positions else (self._cached_balance.get("used", 0) if self._cached_balance else 0.0),
            "realized_pnl": self._cached_balance.get("pnl", 0) if self._cached_balance else 0.0,
            "positions": self._cached_positions or [],
            "is_scanning": self.scanner.is_running if self.scanner else False,
            "is_trading": self.trader.enabled if self.trader else False,
            "engine_state": self._state.name,
        }

    async def _health_check_loop(self):
        while True:
            await asyncio.sleep(60)
            if not self.is_ready or self._state == EngineState.ERROR:
                continue
            try:
                await self.client.get_balance()
            except Exception as e:
                logger.error(f"[HEALTH CHECK] 연결 유실 감지: {e}")
                self._error_msg = str(e)
                self._transition(EngineState.ERROR, "Health Check 실패")
                await self._attempt_recovery_async()

    async def _handle_gap_exit_async(self, sig) -> None:
        """갭 탈출: 해당 심볼에 보유 포지션이 있으면 즉각 시장가 청산"""
        if not self.is_ready or not self.trader or not self.trader.enabled:
            return
        try:
            positions = await self._maybe_await(self.client.get_positions())
            held = [p for p in positions if p.get("symbol") == sig.symbol]
            if not held:
                return
            pos   = held[0]
            side  = pos.get("side", "long")
            logger.warning(f"[GAP EXIT] {sig.symbol} {side.upper()} 갭 감지 → 즉각 시장가 청산 실행")
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, self.close_position, sig.symbol, side)
        except Exception as e:
            logger.error(f"[GAP EXIT ERROR] {sig.symbol} 갭 청산 실패: {e}")

    async def _check_closed_positions_async(self, record_only: bool = False):
        """청산 감지 → CSV/통계/알림 기록. 이어서 보유시간·로테이션·트레일링을 점검한다.

        `record_only=True`는 **기록만** 하고 청산 장치는 전부 건너뛴다.
        헤드리스 러너(bot.py)용이다. bot.py가 이 함수를 호출한 적이 없어서
        거래소 OCO가 자동 체결한 청산이 CSV에 남지 않았다(오프라인 청산으로
        감지만 하고 버림). 기록 경로를 다시 잇되, 조기청산 장치는 그동안
        검증을 거쳐 해제한 것들이므로 record_only 경로에서는 되살리지 않는다.
        [2026-08-27] 8401 v10.1.0에서 확인·수정한 것을 이식.
        """
        if not self.is_ready:
            return
        try:
            raw_positions = await self._maybe_await(self.client.get_positions())
            self._cached_positions = raw_positions # 백그라운드 캐시 업데이트
            self._cached_positions_ts = time.time()  # [v3.1.68] 신선도 갱신
            
            # 잔고도 백그라운드에서 실시간 동기 업데이트
            try:
                raw_balance = await self._maybe_await(self.client.get_balance())
                self._cached_balance = raw_balance
            except Exception as be:
                logger.error(f"백그라운드 잔고 동기화 실패: {be}")

            current = {p["symbol"] for p in raw_positions}
            closed = self._prev_position_symbols - current

            if closed:
                for sym in closed:
                    exit_profile = "SL/TP"
                    if self.trader:
                        exit_profile = getattr(self.trader, "position_exit_profiles", {}).get(sym, "SL/TP")
                    # [v2.14.6] 외부 청산 시 잔여 OCO/알고리즘 주문 취소 보완
                    try:
                        logger.info(f"[ALGO CLOSE] {sym} 외부 청산 감지 → 잔여 알고 주문 취소 시도")
                        await self.client.cancel_algo_orders(sym)
                    except Exception as ae:
                        logger.error(f"[ALGO CLOSE] {sym} 외부 청산 감지 후 알고 주문 취소 실패: {ae}")

                    self._timeout_cooldowns.pop(sym, None)
                    self._timeout_failure_counts.pop(sym, None)
                    if self.trader:
                        self.trader.position_strategies.pop(sym, None)
                        if hasattr(self.trader, 'position_atr_activations'):
                            self.trader.position_atr_activations.pop(sym, None)
                        if hasattr(self.trader, 'position_exit_profiles'):
                            self.trader.position_exit_profiles[sym] = exit_profile
                        self.trader.save_active_positions()
                    
                    try:
                        # [v3.1.54] 부분 체결 분할 청산 누락 방지를 위한 API 딜레이 대기 및 다중 체결 기록
                        await asyncio.sleep(1.5)
                        recent_trades = await self._maybe_await(self.client.get_trade_history(symbol=sym, limit=20))
                        
                        exit_trades = [t for t in recent_trades if t.get("category") == "청산"]
                        
                        try:
                            local_trades = load_local_trade_history()
                        except Exception as le:
                            logger.error(f"로컬 거래 내역 로드 실패: {le}")
                            local_trades = []
                            
                        is_ts = "✅" if sym in self._ts_triggered else ""
                        exit_type = self._infer_exit_type(sym, bool(is_ts), local_trades)
                        
                        # Use the most recent exit_trade for telegram alert and pnl accumulation
                        unlogged_exits = [t for t in exit_trades if not self._is_trade_logged(t)]
                        if not unlogged_exits:
                            continue
                            
                        # Group exit trades by order_id to merge partial fills
                        grouped_exits = {}
                        for t in unlogged_exits:
                            oid = t.get("order_id") or "unknown"
                            if oid not in grouped_exits:
                                grouped_exits[oid] = []
                            grouped_exits[oid].append(t)

                        total_pnl = 0.0
                        total_margin_est = 0.0
                        latest_exit_trade = None
                        latest_pnl_pct_val = 0.0
                        
                        for oid, trades_group in grouped_exits.items():
                            grp_amount = 0.0
                            grp_cost = 0.0
                            grp_pnl = 0.0
                            weighted_price_num = 0.0
                            
                            for t in trades_group:
                                amt = float(t.get("amount", 0))
                                prc = float(t.get("price", 0))
                                grp_amount += amt
                                grp_cost += float(t.get("cost", 0) or 0)
                                grp_pnl += float(t.get("pnl", 0))
                                weighted_price_num += (amt * prc)
                                
                            grp_price = weighted_price_num / grp_amount if grp_amount > 0 else 0.0
                            last_t = trades_group[-1]
                            
                            # 로컬 거래 내역에서 진입가와 레버리지를 탐색하여 정확한 margin_est 산출
                            entry_price = None
                            leverage = self.cfg.LEVERAGE
                            for local in reversed(local_trades):
                                if local["symbol"] == sym and local["category"] in ("진입", "*진입"):
                                    leverage = local.get("leverage") or leverage
                                    entry_price = local.get("price")
                                    break
                                    
                            is_exit_long = str(last_t.get("side", "")).lower() in ("sell", "short")
                            if entry_price and float(entry_price) > 0 and grp_price > 0 and grp_amount > 0:
                                contract_size = 1.0
                                if self.client._markets and sym in self.client._markets:
                                    contract_size = float(self.client._markets[sym].get('contractSize', 1.0))
                                elif grp_cost > 0:
                                    contract_size = grp_cost / (grp_price * grp_amount)
                                
                                calculated_pnl = (float(grp_price) - float(entry_price)) * grp_amount * contract_size if is_exit_long else (float(entry_price) - float(grp_price)) * grp_amount * contract_size
                                margin_est = (float(entry_price) * grp_amount * contract_size) / float(leverage) if leverage else 0.0
                                
                                if (grp_pnl > 0 and calculated_pnl < 0) or (grp_pnl < 0 and calculated_pnl > 0):
                                    logger.warning(f"[PNL SYNC] {sym} PnL 부호 엇갈림 방지: 거래소 PnL={grp_pnl:+.4f} -> 로컬 계산 PnL={calculated_pnl:+.4f}")
                                    grp_pnl = calculated_pnl
                                    
                                grp_pnl_pct = (grp_pnl / margin_est) * 100 if margin_est > 0 else 0.0
                            else:
                                margin_est = grp_cost / float(leverage) if leverage else 0
                                grp_pnl_pct = (grp_pnl / margin_est) * 100 if margin_est > 0 else 0.0
                            
                            total_pnl += grp_pnl
                            total_margin_est += margin_est
                            latest_exit_trade = last_t
                            latest_pnl_pct_val = grp_pnl_pct
                            
                            combined_tids = "|".join([str(t.get("trade_id") or t.get("id") or "") for t in trades_group])

                            csv_log({
                                "timestamp": last_t.get("timestamp", datetime.now(timezone(timedelta(hours=9)))),
                                "symbol": sym,
                                "type": "청산",
                                "side": last_t.get("side", ""),
                                "price": round(grp_price, 6),
                                "amount": grp_amount,
                                "pnl_usdt": grp_pnl,
                                "pnl_pct": grp_pnl_pct,
                                "exit_type": exit_type,
                                "is_ts": is_ts,
                                "leverage": leverage,
                                "order_id": oid if oid != "unknown" else last_t.get("order_id", ""),
                                "trade_id": combined_tids,
                                "trade_mode": self._entry_trade_mode(sym),
                                })
                                
                        if sym in self._ts_triggered:
                            self._ts_triggered.discard(sym)
                            
                        pnl = total_pnl
                        exit_trade = latest_exit_trade
                        pnl_pct_val = (total_pnl / total_margin_est) * 100 if total_margin_est > 0 else latest_pnl_pct_val
                        
                        if self.trader and hasattr(self.trader, "position_exit_profiles"):
                            self.trader.position_exit_profiles.pop(sym, None)
                    except Exception as e:
                        logger.error(f"청산 CSV 기록 실패: {e}")
                        exit_trade = None
                        pnl = 0.0
                        pnl_pct_val = 0.0

                    stats_store.record_result(pnl)
                    if self.trader:
                        self.trader.daily_pnl_usdt = round(self.trader.daily_pnl_usdt + pnl, 4)
                        # [v7.9.0] 청산 후 재진입 금지창 60초 → REENTRY_BLOCK_MIN(기본 15분)
                        # 손절 직후 같은 자리 연쇄 재진입(이력상 손실 66건 중 23건) 봉쇄
                        _block_sec = int(float(getattr(self.cfg, "REENTRY_BLOCK_MIN", 15.0)) * 60)
                        self.trader.trigger_symbol_cooldown(sym, max(_block_sec, 60))
                        # [연패쿨다운] 2연패 시 해당 종목 장기 진입차단(위 쿨다운 위에 덮어씀)
                        self.trader.register_trade_result(sym, pnl)
                    
                    # 청산 알림 발송
                    side_str = exit_trade.get("side", "") if exit_trade else ""
                    price_str = exit_trade.get("price", 0.0) if exit_trade else 0.0
                    emoji = "🔥" if pnl >= 0 else "❄️"
                    send_telegram_alert(
                        f"{emoji} *[포지션 청산 완료]*\n"
                        f"종목: {sym}\n"
                        f"구분: {side_str.upper()} 청산\n"
                        f"청산가: {price_str}\n"
                        f"실현 손익: {pnl:+.4f} USDT\n"
                        f"수익률: {pnl_pct_val:+.2f}%"
                    )
                    logger.info(f"[CLOSED] {sym} PnL={pnl:+.4f} -> {'WIN' if pnl >= 0 else 'LOSS'}")
                    self.check_auto_mode_switch()

            if not record_only and self.cfg.MAX_HOLDING_HOURS > 0:
                now_ms = time.time() * 1000
                timeout_ms = self.cfg.MAX_HOLDING_HOURS * 3600 * 1000
                for p in raw_positions:
                    entry_ts = p.get("timestamp")
                    if entry_ts and (now_ms - entry_ts) > timeout_ms:
                        sym = p["symbol"]
                        side = p["side"]
                        # [v7.9.0] 수익 중 포지션은 하드캡까지 시간청산 유예
                        # (TP 1:2 도달 전 승자 조기절단이 실현 손익비를 1.17로 깎던 문제)
                        if bool(getattr(self.cfg, "TIMEOUT_SKIP_PROFITABLE", True)):
                            _pnl_now = float(p.get("pnl_usdt", 0) or 0)
                            _hard_ms = float(getattr(self.cfg, "MAX_HOLDING_HARD_HOURS", 24.0)) * 3600 * 1000
                            if _pnl_now > 0 and (now_ms - entry_ts) < _hard_ms:
                                logger.debug(f"[TIMEOUT SKIP] {sym} 수익 중(+{_pnl_now:.4f}) → 하드캡까지 유예")
                                continue
                        now_sec = time.time()
                        if sym in self._timeout_cooldowns and (now_sec - self._timeout_cooldowns[sym]) < 30.0:
                            logger.info(f"[TIMEOUT COOLDOWN] {sym} 강제청산 실패 쿨다운 대기 중... 남은 시간: {30.0 - (now_sec - self._timeout_cooldowns[sym]):.1f}초")
                            continue

                        logger.warning(f"[TIMEOUT] {sym} {side} - {self.cfg.MAX_HOLDING_HOURS}시간 초과 강제청산 실행")
                        success = await self.close_position_async(sym, side)
                        if success:
                            self._timeout_cooldowns.pop(sym, None)
                            self._timeout_failure_counts.pop(sym, None)
                            if self.trader:
                                self.trader.trigger_symbol_cooldown(sym, 60)
                        else:
                            self._timeout_cooldowns[sym] = now_sec
                            self._timeout_failure_counts[sym] = self._timeout_failure_counts.get(sym, 0) + 1
                            logger.error(f"[TIMEOUT ERROR] {sym} 강제청산 실패 - 30초 쿨다운 적용 (연속 실패: {self._timeout_failure_counts[sym]}/10)")
                            
                            # 10회 연속 실패 시 봇의 자동매매를 정지하고 경보 발송
                            if self._timeout_failure_counts[sym] >= 10:
                                logger.critical(f"[FAIL-SAFE HALT] {sym} 강제청산 10회 연속 실패! 시스템 안전을 위해 자동매매를 긴급 정지합니다.")
                                send_telegram_alert(
                                    f"🚨🚨🚨 *[긴급 자동매매 정지 (FAIL-SAFE)]*\n"
                                    f"종목: {sym}\n"
                                    f"사유: 최대 보유시간 초과 강제청산 10회 연속 실패\n"
                                    f"결과: 자동매매를 긴급 비활성화 하였습니다. 계정 상태 및 API를 즉시 점검하십시오."
                                )
                                if self.trader:
                                    self.trader.disable()


            # --- [HARD SL/TP GUARD] 거래소 OCO 유실 대비 로컬 최후 방어선 ---
            if not record_only:
                for p in raw_positions:
                    sym = p["symbol"]
                    side = p["side"]
                    pnl_pct = float(p.get("pnl_pct", 0.0))
                    
                    # [BUGFIX] pnl_pct는 백분율(%, 예: -2.5)이므로 limit도 100을 곱해야 함.
                    sl_limit = getattr(self.cfg, "STOP_LOSS_PCT", 0.02) * 150.0  # 0.02 * 150 = 3.0(%)
                    tp_limit = getattr(self.cfg, "TAKE_PROFIT_PCT", 0.04) * 150.0 # 0.04 * 150 = 6.0(%)
                    
                    is_hard_sl = pnl_pct <= -sl_limit
                    is_hard_tp = pnl_pct >= tp_limit
                    
                    if is_hard_sl or is_hard_tp:
                        now_sec = time.time()
                        if sym in self._timeout_cooldowns and (now_sec - self._timeout_cooldowns[sym]) < 30.0:
                            continue
                            
                        reason = "HARD_SL" if is_hard_sl else "HARD_TP"
                        logger.warning(f"[HARD GUARD] {sym} {side} - 비상 {reason} 강제청산 발동 (현재수익률: {pnl_pct:.2f}%)")
                        
                        # 비동기 청산 집행
                        success = await self.close_position_async(sym, side)
                        if success:
                            self._timeout_cooldowns.pop(sym, None)
                            if self.trader:
                                self.trader.trigger_symbol_cooldown(sym, 60)
                        else:
                            self._timeout_cooldowns[sym] = now_sec
                            logger.error(f"[{reason} ERROR] {sym} 비상 강제청산 실패 - 30초 쿨다운")
            
            if self._prev_position_symbols != current:
                self._prev_position_symbols = current
                self.save_engine_states()
            if record_only:
                return
            await self._run_position_rotation_check_async(raw_positions)

            # [2026-08-28] 청산 경로 단일 트레이더 게이트.
            # 종전에는 trade_lock이 '진입'만 통제했다. trader.enable()은 락을 확인하지만
            # 청산 관리자는 스캐너 루프에 실려 있어 락과 무관하게 돌았다. 그래서
            # app.py의 대시보드 엔진(주석상 '모니터 전용')이 실제로는
            # client.close_position()을 직접 호출해, bot.py가 설계한 OCO(RR 1:2)를
            # 앞질러 잘라냈다. 실측(2026-08-28): 대시보드는 17:26 기동이라 18:49자
            # config 수정분을 못 읽고 USE_TRAILING_STOP=true인 옛 설정으로 샹들리에
            # 트레일링을 계속 돌렸고, [TRAILING STOP] 청산 발동 기록이
            # streamlit_server.log에만 남았다(bot_engine.log에는 없다).
            # 락 보유자가 없으면 아무도 청산 관리를 하지 않는다 — 진입도 같은 락에
            # 묶여 있어 관리 대상이 생기지 않고, 이미 열린 포지션은 진입 시 거래소에
            # 건 SL/TP 보호주문(_place_protective)이 지킨다.
            _lock_holder = trade_lock_holder_pid()
            if _lock_holder == os.getpid():
                await self.trailing_stop_manager.check_async(raw_positions)
            elif not getattr(self, "_exit_gate_logged", False):
                self._exit_gate_logged = True
                logger.info(
                    f"[EXIT GATE] 이 프로세스(PID {os.getpid()})는 트레이드 락 "
                    f"보유자(PID {_lock_holder or '없음'})가 아님 → 청산 관리 비활성 "
                    f"(모니터 전용). 청산은 락 보유 프로세스가 단독 수행."
                )
        except Exception as e:
            logger.error(f"청산 감지 오류: {e}")



    async def _run_position_rotation_check_async(self, raw_positions: List[Dict]):
        if not self.cfg.ROTATION_ENABLED:
            return

        scan_results = await self._maybe_await(self.scanner.get_results())
        scan_signals = [s for s in scan_results if s.get("signal") in ("long", "short") and s.get("strength", 0) >= 60]
        if len(scan_signals) < self.cfg.ROTATION_MIN_SIGNALS:
            return

        now_ms = time.time() * 1000
        stale_limit_ms = self.cfg.ROTATION_STALE_HOURS * 3600 * 1000

        for p in raw_positions:
            entry_ts = p.get("timestamp")
            if not entry_ts:
                continue

            if (now_ms - entry_ts) > stale_limit_ms:
                if await self._is_flow_bad_async(p):
                    sym = p["symbol"]
                    side = p["side"]
                    pnl = float(p.get("pnl_usdt", 0.0))
                    pnl_pct = float(p.get("pnl_pct", 0.0))
                    
                    logger.warning(f"[ROTATION] {sym} {side} 정체 포지션 감지. 시장가 청산 실행.")
                    
                    close_res = False
                    for retry in range(3):
                        close_res = await self.close_position_async(sym, side)
                        if close_res:
                            break
                        logger.warning(f"[ROTATION RETRY] {sym} 청산 시도 {retry+1}/3 실패")
                        await asyncio.sleep(3.0)

                    if close_res:
                        if self.trader:
                            self.trader.trigger_symbol_cooldown(sym, 60)
                        csv_log({
                            "timestamp": datetime.now(timezone(timedelta(hours=9))),
                            "symbol": sym,
                            "type": "청산(로테이션)",
                            "side": side,
                            "price": p.get("mark_price", 0.0),
                            "amount": p.get("size", 0.0),
                            "pnl_usdt": pnl,
                            "pnl_pct": pnl_pct,
                            "leverage": p.get("leverage", self.cfg.LEVERAGE),
                            "order_id": f"ROT-{int(now_ms)}",
                            "trade_mode": self._entry_trade_mode(p.get("symbol", "")),
                            "trade_id": f"ROT-{int(now_ms)}",
                        })
                        stats_store.record_result(pnl)
                        if self.trader:
                            self.trader.daily_pnl_usdt = round(self.trader.daily_pnl_usdt + pnl, 4)

    async def _maybe_await(self, value):
        if inspect.isawaitable(value):
            return await value
        return value

    def _logged_trade_keys(self) -> set:
        try:
            keys = set()
            for t in load_local_trade_history():
                tid_str = str(t.get("trade_id") or "")
                if "|" in tid_str:
                    for sub_tid in tid_str.split("|"):
                        if sub_tid.strip():
                            t_copy = dict(t)
                            t_copy["trade_id"] = sub_tid.strip()
                            keys.add(_trade_dedupe_key(t_copy))
                else:
                    keys.add(_trade_dedupe_key(t))
            return keys
        except Exception as e:
            logger.error(f"로컬 거래 키 로드 실패: {e}")
            return set()

    def _exchange_trade_key(self, trade: Dict):
        normalized = {
            "timestamp": trade.get("timestamp"),
            "symbol": trade.get("symbol"),
            "category": trade.get("category"),
            "side": trade.get("side"),
            "price": trade.get("price"),
            "amount": trade.get("amount"),
            "pnl": trade.get("pnl"),
            "order_id": _normalize_id(trade.get("order_id") or trade.get("order")),
            "trade_id": _normalize_id(trade.get("trade_id") or trade.get("id")),
        }
        return _trade_dedupe_key(normalized)

    def _is_trade_logged(self, trade: Dict) -> bool:
        return self._exchange_trade_key(trade) in self._logged_trade_keys()

    @staticmethod
    def _remaining_lots(local_trades: List[Dict]) -> Dict[tuple, float]:
        lots: Dict[tuple, float] = {}
        for trade in sorted(local_trades, key=lambda x: x["timestamp"]):
            direction = get_position_direction(trade["category"], trade["side"])
            key = (trade["symbol"], direction)
            amount = float(trade.get("amount") or 0)
            if trade["category"] in ("진입", "*진입"):
                lots[key] = lots.get(key, 0.0) + amount
            elif trade["category"] in ("청산", "청산(로테이션)"):
                lots[key] = max(0.0, lots.get(key, 0.0) - amount)
        return lots

    @staticmethod
    def _infer_trade_category(trade: Dict, lots: Dict[tuple, float]) -> str:
        reported = trade.get("category")
        if reported in ("청산", "청산(로테이션)"):
            return "청산"

        side = str(trade.get("side", "")).lower()
        symbol = trade.get("symbol")
        if side == "sell" and lots.get((symbol, "LONG"), 0.0) > 1e-8:
            return "청산"
        if side == "buy" and lots.get((symbol, "SHORT"), 0.0) > 1e-8:
            return "청산"
        return "진입"

    @staticmethod
    def _apply_trade_to_lots(trade: Dict, category: str, lots: Dict[tuple, float]) -> None:
        symbol = trade.get("symbol")
        amount = float(trade.get("amount") or 0)
        direction = get_position_direction(category, trade.get("side", ""))
        key = (symbol, direction)
        if category == "진입":
            lots[key] = lots.get(key, 0.0) + amount
        else:
            lots[key] = max(0.0, lots.get(key, 0.0) - amount)

    async def _is_flow_bad_async(self, p: Dict) -> bool:
        symbol = p["symbol"]
        side = p["side"]
        entry_price = float(p.get("entry_price") or 0.0)
        current_price = float(p.get("mark_price") or p.get("current_price") or 0.0)
        
        if entry_price <= 0 or current_price <= 0:
            return False

        check_type = self.cfg.ROTATION_FLOW_CHECK
        if check_type == "momentum":
            try:
                df = await self._maybe_await(self.client.get_ohlcv(symbol, timeframe="15m", limit=50))
                if not df.empty and len(df) >= 20:
                    ema = df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
                    if "long" in side.lower() or "buy" in side.lower():
                        return current_price < ema
                    else:
                        return current_price > ema
            except Exception:
                return False
        elif check_type == "flat":
            try:
                entry_ts = p.get("timestamp")
                if entry_ts:
                    now_ms = time.time() * 1000
                    duration_min = int((now_ms - entry_ts) / 60000)
                    limit = min(max(duration_min, 10), 200)
                    df = await self._maybe_await(self.client.get_ohlcv(symbol, timeframe="1m", limit=limit))
                    if not df.empty:
                        highs = df["high"].max()
                        lows = df["low"].min()
                        amplitude = (highs - lows) / entry_price
                        return amplitude < 0.0025
            except Exception:
                return False
        elif check_type == "time":
            pnl_pct = float(p.get("pnl_pct") or 0.0)
            return -2.0 <= pnl_pct <= 1.0

        return False


    def check_auto_mode_switch(self):
        """
        매매방향 전환 기준:
        - 초기화 직후 첫 3~4회 청산 시 3회 손실 발생 시 (xxx, xxxO, xxOx, xOxx, xxxx)
        - 5회 이상 청산 거래 누적 시 최근 5번 중 3번 이상 손실 발생 시
        디스크(data/switch_state.json) 영속 기록으로 중복 스위칭을 방지하고, 전환 시 디스코드 웹훅 알림을 즉시 발송합니다.
        """
        import os
        import sys
        import json
        import time
        from datetime import datetime

        if not getattr(self.cfg, "USE_AUTO_MODE_SWITCH", True):
            return

        try:
            from core.history_helper import load_local_trade_history, aggregate_and_pair_trades
            base_path = getattr(self, "base_dir", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(base_path, "data")
            os.makedirs(data_dir, exist_ok=True)
            stats_file = os.path.join(data_dir, "stats.json")
            perf_start_time = None
            if os.path.exists(stats_file):
                try:
                    with open(stats_file, "r", encoding="utf-8") as stf:
                        stdata = json.load(stf)
                        perf_start_time = stdata.get("perf_start_time")
                except Exception:
                    pass

            raw_trades = load_local_trade_history()
            paired = aggregate_and_pair_trades(raw_trades)

            # 청산 완료된 거래 중 유령/무승부(0.0) 제외 후 시간순(오래된 순) 정렬
            closed_trades = [
                x for x in paired 
                if x.get("status") == "청산 완료" 
                and x.get("exit_time") is not None
                and round(float(x.get("pnl_usdt") or 0.0), 4) != 0.0
            ]
            closed_trades.sort(key=lambda x: str(x.get("exit_time")))

            N = len(closed_trades)
            if N < 3:
                return

            base_path = getattr(self, "base_dir", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(base_path, "data")
            os.makedirs(data_dir, exist_ok=True)
            state_file = os.path.join(data_dir, "switch_state.json")

            sdata = {}
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as sf:
                        sdata = json.load(sf)
                except Exception:
                    sdata = {}

            last_switched_key = sdata.get("last_switched_key")
            last_switched_on_count = sdata.get("last_switched_on_count", -1)
            # [2026-09-02] 쿨다운이 조용히 꺼지던 문제 방어.
            # 이 값이 -1이면 아래 쿨다운 조건이 통째로 무시된다. 실제로 외부
            # 정비 스크립트(8888/hard_fix_all.py)가 -1을 되써 9봇 전부 쿨다운이
            # 풀려 있었다. 값이 손상돼도 last_switched_key로 시점을 복원해
            # "스위칭 후 최소 3거래" 보호가 유지되게 한다.
            try:
                last_switched_on_count = int(last_switched_on_count)
            except (TypeError, ValueError):
                last_switched_on_count = -1
            latest_key = str(closed_trades[-1].get("exit_time") or closed_trades[-1].get("timestamp"))
            if last_switched_on_count < 0 and last_switched_key:
                for _i, _t in enumerate(closed_trades, 1):
                    if str(_t.get("exit_time")) == str(last_switched_key):
                        last_switched_on_count = _i
                        break

            # 동일 마지막 체결에 대해 이미 스위칭을 수행했으면 중복 스위칭 방지
            if last_switched_key == latest_key:
                return

            # [2026-09-03 기준 정리] 스위칭 후에는 **승패 기록을 리셋**하고
            # 그 이후 거래만으로 재전환을 판단한다.
            #
            # 종전 방식의 문제: 쿨다운 3건이 지나면 '전체 이력의 최근 5전'을 봤는데,
            # 그 5전에 스위칭 이전 거래가 2건 섞여 들어갔다. 방향을 이미 바꿨는데
            # 바꾸기 전의 패배가 다시 재전환 근거가 되니 기준이 애매했다.
            #
            # 새 기준 (예: 순방향 시작 → 승승패패패 → 역방향 전환)
            #   · 이후 '패' 1건    → 새 기록 1건, 판단 보류 (역방향 유지)
            #   · 이후 '패' 2건    → 새 기록 2건, 판단 보류 (역방향 유지)
            #   · 이후 '패' 3건    → 새 기록 3건이 전부 패 → 재전환
            # 새 기록이 3건 미만이면 판단하지 않으므로, 쿨다운 장치가 따로 필요 없다.
            _base = last_switched_on_count if last_switched_on_count and last_switched_on_count > 0 else 0
            if _base > N:
                _base = 0          # 이력이 줄어든 흔적(초기화 등) — 기준점을 되돌린다
            window = closed_trades[_base:]
            M = len(window)
            if M < 3:
                return

            should_switch = False
            reason_msg = ""
            pattern_str = ""

            def _lost(_t):
                return float(_t.get("pnl_usdt") or 0.0) < 0.0

            if M >= 5:
                # [5전 3패] 스위칭 이후 기록의 최근 5전 중 3패 이상이면 전환
                recent_5 = window[-5:]
                losses = sum(1 for t in recent_5 if _lost(t))
                if losses >= 3:
                    should_switch = True
                    seq = "".join(["x" if _lost(t) else "O" for t in recent_5])
                    pattern_str = seq
                    reason_msg = f"스위칭 후 5전 중 {losses}패({seq})"
            elif all(_lost(t) for t in window[-3:]):
                # 새 기록이 3~4건뿐일 때는 '전부 패'만 전환 근거로 인정
                should_switch = True
                pattern_str = "xxx"
                reason_msg = f"스위칭 후 3연패(xxx) 발생 (새 기록 {M}건)"

            if should_switch:
                try:
                    with open(state_file, "w", encoding="utf-8") as sf:
                        json.dump({
                            "last_switched_key": latest_key,
                            "last_switched_on_count": N,
                            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "reason": reason_msg,
                            "pattern": pattern_str
                        }, sf, indent=2)
                except Exception:
                    pass

                self._last_switched_trade_keys = (latest_key,)
                cur_mode = getattr(self.cfg, "USE_BLUEFROG", True)
                new_mode = not cur_mode
                self.cfg.USE_BLUEFROG = new_mode
                self.cfg.save_settings()

                old_mode_str = "🐸 청개구리 모드(역매매) [역]" if cur_mode else "🎯 정방향 매매 모드 [순]"
                new_mode_str = "🐸 청개구리 모드(역매매) [역]" if new_mode else "🎯 정방향 매매 모드 [순]"

                logger.warning(f"[AUTO MODE SWITCH] {reason_msg}! 매매방향 대칭 자동 스위칭: {old_mode_str} ➡️ {new_mode_str}")

                try:
                    from core.alert import send_telegram_alert
                    alert_msg = (
                        f"⚡ **매매방향 자동 스위칭 발동!**\n"
                        f"----------------------------------------\n"
                        f"📊 **발동 사유**: {reason_msg}\n"
                        f"🔄 **모드 전환**: {old_mode_str} ➡️ **{new_mode_str}**\n"
                        f"⏱ **전환 시각**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"----------------------------------------\n"
                        f"💡 대칭 반전 매매가 즉시 적용됩니다."
                    )
                    send_telegram_alert(alert_msg)
                except Exception as ae:
                    logger.error(f"[AUTO MODE SWITCH] 알림 발송 실패: {ae}")
        except Exception as e:
            logger.error(f"[AUTO MODE SWITCH] 오류 발생: {e}")
