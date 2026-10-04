"""
전종목 실시간 스캐너 (비동기 엔터프라이즈 버전)
OKX USDT 선물 전종목 순환 스캔 → 신호 감지
"""
import asyncio
import logging
import pandas as pd
from typing import List, Dict, Callable, Optional, Awaitable, Union
from datetime import datetime

from core.exchange import OKXClient
from core.strategy import StrategyEngine, Signal
from core.regime_router import StrategyRouter
from core.config import CFG

logger = logging.getLogger(__name__)


class Scanner:
    """
    비동기 전종목 스캐너
    - 전종목을 순환 스캔하며 신호 포착
    """

    def __init__(self, client: OKXClient):
        self.client = client
        # [2026-09-04] 국면 라우터로 교체(8402에서 검증된 구조 이식).
        # 얼굴(cfg/client/update_trend/generate_signal)이 같아 이 한 줄로 끝난다.
        # USE_REGIME_ROUTER=False면 내부에서 기존 볼린저 평균회귀로 되돌아간다.
        self.strategy = StrategyRouter()
        self.cfg = CFG
        self.ws_client = None

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = None

        # 공유 상태
        self.scan_results: List[Dict] = []
        self.last_scan_time: Optional[datetime] = None
        self.scan_count: int = 0
        self.log_buffer: List[str] = []

        self._ohlcv_cache: Dict[str, pd.DataFrame] = {}
        self._ohlcv_cache_ts: Dict[str, int] = {}

        # 콜백: 신호 발생 시 (async/sync 겸용)
        self.on_signal: Optional[Union[Callable[[Signal], None], Callable[[Signal], Awaitable[None]]]] = None
        # 콜백: 스캔 1회 완료 시
        self.on_scan_complete: Optional[Union[Callable[[], None], Callable[[], Awaitable[None]]]] = None
        # 콜백: 갭 탈출 감지 시 (보유 포지션 즉각 청산)
        self.on_gap_exit: Optional[Union[Callable[[Signal], None], Callable[[Signal], Awaitable[None]]]] = None

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        self._log_sync("[SCANNER] 스캔 엔진 시작 (Async)")
        
        # 실시간 웹소켓 구독 감시 태스크 가동
        # [perf/stability] 스캔 루프는 이미 REST(get_ohlcv) 전용이라 WS 데이터를 쓰지 않는다.
        #   WS는 네트워크 blip 시 ccxt async WS teardown('Bad file descriptor'→
        #   'Event loop is closed')로 엔진을 죽이고 재연결 지연·로그 폭주만 유발 → 기본 OFF.
        if getattr(self.cfg, "USE_WEBSOCKET", False):
            try:
                symbols = self.client.get_all_usdt_swap_symbols()
                asyncio.create_task(self._start_ws_client_async(symbols))
            except Exception as e:
                logger.error(f"[SCANNER] 웹소켓 시작 실패: {e}")
        else:
            self._log_sync("[SCANNER] 웹소켓 비활성(REST 전용) — 안정성 우선")

    async def _start_ws_client_async(self, symbols: List[str]):
        try:
            tickers = await self.client.get_tickers()
            _wl = getattr(self.cfg, "SYMBOL_WHITELIST", []) or []
            if _wl:  # [v7.9.1] 화이트리스트 우선
                symbols = [s for s in symbols if s in _wl]
            elif tickers and self.cfg.SCAN_TOP_N > 0:
                symbols = sorted(
                    symbols,
                    key=lambda s: tickers.get(s, {}).get("volume", 0),
                    reverse=True
                )[:self.cfg.SCAN_TOP_N]
            
            from core.websocket_client import WebSocketClient
            self.ws_client = WebSocketClient(self)
            self.ws_client.start(symbols)
        except Exception as e:
            logger.error(f"[WS INIT] 웹소켓 초기 설정 및 기동 실패: {e}")

    async def stop(self):
        self._running = False
        if self.ws_client:
            try:
                await self.ws_client.stop()
            except Exception as wse:
                logger.error(f"웹소켓 클라이언트 중지 실패: {wse}")
            self.ws_client = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._log_sync("[SCANNER] 스캔 엔진 중지")

    @property
    def is_running(self) -> bool:
        return self._running

    async def _get_ohlcv_cached(self, sym: str) -> pd.DataFrame:
        # [Hybrid Fallback] 웹소켓 클라이언트가 정상 작동하여 캐시 데이터가 들어있다면 REST 조회 우회
        if self.ws_client and self.ws_client._running:  # [WS깨짐대응] 패스트패스 비활성→REST 신선갱신
            async with self.lock:
                cached = self._ohlcv_cache.get(sym)
            if cached is not None and not cached.empty:
                return cached

        cached = self._ohlcv_cache.get(sym)
        self._did_network_fetch = False  # [지표] 이번 호출에서 실제 네트워크 조회했는지

        if cached is None or cached.empty:
            df = await self.client.get_ohlcv(sym, limit=300)
            self._did_network_fetch = True
            if not df.empty:
                self._ohlcv_cache[sym] = df
                last_ts = df.index[-1]
                self._ohlcv_cache_ts[sym] = int(last_ts.timestamp() * 1000)
                self._log_sync(f"[CACHE] {sym} 초기 로드 {len(df)}봉")
            return df

        # ── 증분 갱신 (마지막 3봉) ──
        try:
            new_df = await self.client.get_ohlcv(sym, limit=3)
            self._did_network_fetch = True
            if new_df is None or new_df.empty:
                # [FIX] 조용히 stale 캐시 반환하던 지점 → 경고 노출
                logger.warning(f"[CACHE] {sym} 증분 조회 빈 응답 → 기존 캐시 유지")
            else:
                merged = pd.concat([cached, new_df])
                merged = merged[~merged.index.duplicated(keep='last')]
                merged = merged.sort_index().tail(300)
                self._ohlcv_cache[sym] = merged
                self._ohlcv_cache_ts[sym] = int(merged.index[-1].timestamp() * 1000)
                cached = merged
        except Exception as e:
            logger.warning(f"[CACHE] {sym} 증분 업데이트 실패, 캐시 사용: {e}")

        # ── [WATCHDOG] 갱신 후에도 마지막 봉이 stale이면 강제 풀 리로드 ──
        #    증분 조회가 조용히 실패/고착돼 캔들이 안 늘면 DualBB 트리거가 영영 안 터진다.
        try:
            stale_min = self._tf_minutes() * 2  # 봉 2개분 이상 지연 = 고착으로 판정
            last = cached.index[-1]
            if getattr(last, "tzinfo", None) is not None:
                last = last.tz_convert("UTC").tz_localize(None)
            now_utc = pd.Timestamp.utcnow().tz_localize(None)
            age_min = (now_utc - last).total_seconds() / 60.0
            if age_min > stale_min:
                logger.warning(f"[WATCHDOG] {sym} 캔들 고착 감지(age {age_min:.0f}분 > {stale_min:.0f}분) → 강제 재조회")
                fresh = await self.client.get_ohlcv(sym, limit=300)
                self._did_network_fetch = True
                if fresh is not None and not fresh.empty:
                    self._ohlcv_cache[sym] = fresh
                    self._ohlcv_cache_ts[sym] = int(fresh.index[-1].timestamp() * 1000)
                    cached = fresh
        except Exception as e:
            logger.warning(f"[WATCHDOG] {sym} 신선도 점검 실패: {e}")

        return cached

    def _tf_minutes(self) -> int:
        """cfg.TIMEFRAME('5m'/'1h'/'1d')를 분으로 환산."""
        tf = str(getattr(self.cfg, "TIMEFRAME", "5m")).strip().lower()
        try:
            if tf.endswith("m"):
                return max(1, int(tf[:-1]))
            if tf.endswith("h"):
                return max(1, int(tf[:-1]) * 60)
            if tf.endswith("d"):
                return max(1, int(tf[:-1]) * 1440)
        except ValueError:
            pass
        return 5

    async def clear_cache(self):
        async with self.lock:
            self._ohlcv_cache.clear()
            self._ohlcv_cache_ts.clear()
        self._log_sync("[CACHE] OHLCV 캐시 초기화 완료")

    async def _scan_loop(self):
        # [HANG GUARD] 단일 스캔 회차가 네트워크 await(get_tickers/get_ohlcv 등)에서
        # 무한 대기하면 루프 전체가 멈추고 scan_count도 안 늘어 워치독이 못 살린다.
        # → wait_for로 회차마다 강제 타임아웃을 걸어 멈춘 await를 취소하고 다음 회차로 넘어간다.
        scan_timeout = getattr(self.cfg, "SCAN_TIMEOUT_SEC", 90)
        while self._running:
            try:
                await asyncio.wait_for(self._run_once(), timeout=scan_timeout)
            except asyncio.CancelledError:
                break
            except asyncio.TimeoutError:
                logger.warning(f"[HANG GUARD] 스캔 회차 {scan_timeout}초 초과 → 강제 취소 후 재시도")
                self._log_sync(f"[HANG GUARD] 스캔 {scan_timeout}초 초과 → 재시도")
            except Exception as e:
                logger.error(f"스캔 루프 오류: {e}")
                self._log_sync(f"[ERR] 스캔 오류: {e}")
            await asyncio.sleep(self.cfg.SCAN_INTERVAL_SEC)

    async def _run_once(self):
        # 스캔 회차 동안 고정된 설정을 바라보도록 스냅샷 생성 및 전략 모듈에 바인딩
        cfg_snap = self.cfg.copy()
        self.strategy.cfg = cfg_snap
        # [Triple-Indicator] 1시간봉 추세 조회용 클라이언트 주입
        self.strategy.client = self.client

        symbols = self.client.get_all_usdt_swap_symbols()

        try:
            tickers = await self.client.get_tickers()
        except Exception as e:
            self._log_sync(f"[ERR] Ticker 일괄 조회 예외 발생: {e}")
            return

        if not tickers:
            self._log_sync("[WARN] 일괄 조회된 Ticker가 없습니다. 스캔 건너뜀.")
            return


        # [v7.9.1 화이트리스트] 지정 시 해당 심볼만 스캔·진입 (블랙리스트·상위N보다 우선)
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
                    self._log_sync(f"[SCAN] 블랙리스트 {removed}개 제외: {blacklist}")

            if cfg_snap.SCAN_TOP_N > 0:
                symbols = sorted(
                    symbols,
                    key=lambda s: tickers.get(s, {}).get("volume", 0),
                    reverse=True
                )[:cfg_snap.SCAN_TOP_N]

        self._log_sync(f"[SCAN] 스캔 시작: {len(symbols)}개 페어 (캐시 {len(self._ohlcv_cache)}개 보유)")

        results = []
        signal_count = 0
        cache_hit = 0
        api_calls = 0
        
        for sym in symbols:
            if not self._running:
                break
            try:
                ticker = tickers.get(sym)
                if not ticker:
                    ticker = tickers.get(sym.split(":")[0])

                if not ticker:
                    continue

                vol = ticker.get("volume", 0)
                if vol < cfg_snap.MIN_VOLUME_USDT:
                    continue

                bid = ticker.get("bid", 0)
                ask = ticker.get("ask", 0)
                if bid and ask and ask > 0:
                    spread_pct = (ask - bid) / ask * 100
                    if spread_pct > cfg_snap.MAX_SPREAD_PCT:
                        continue

                was_cached = sym in self._ohlcv_cache  # (뒤쪽 sleep 스로틀에서 사용)
                df = await self._get_ohlcv_cached(sym)
                # [FIX] 증분/워치독 재조회도 실제 네트워크 호출로 정확히 계상
                if getattr(self, "_did_network_fetch", False):
                    api_calls += 1
                else:
                    cache_hit += 1

                if df.empty:
                    continue

                # [Triple-Indicator] 1시간봉 추세 캐시 갱신 (5분 throttle 내장)
                await self.strategy.update_trend(sym)
                # 🚀 수익성부스터 실시간 파라미터 전달 (OKX 펀딩비 추출)
                fr = 0.0
                try:
                    info = ticker.get("info", {})
                    fr = float(info.get("fundingRate") or 0.0)
                except Exception:
                    pass
                sig = self.strategy.generate_signal(df, sym, funding_rate=fr)
                results.append({
                    "symbol": sym,
                    "price": ticker.get("last", 0),
                    "change_pct": ticker.get("change_pct", 0),
                    "volume_m": round(vol / 1_000_000, 1),
                    "signal": sig.direction,
                    "strength": sig.strength,
                    "regime": getattr(sig, "regime", "Unknown"),
                    "strategy_type": getattr(sig, "strategy_type", "None"),
                    "booster": getattr(sig, "booster_tag", ""),
                    "rsi": round(sig.rsi, 1),
                    "bb_mid": round(getattr(sig, "ema200", 0.0), 4),      # BB 중심선
                    "bb_pos_pct": round(getattr(sig, "macd_hist", 0.0), 2),  # 중심 대비 위치(%)
                    "stage1_ok": bool(getattr(sig, "ema_ok", False)),    # ①3SD 이탈
                    "stage2_ok": bool(getattr(sig, "bb_ok", False)),     # ②2SD 복귀+트리거
                    "stage3_ok": bool(getattr(sig, "macd_ok", False)),   # ③트리거 돌파
                    "reason": sig.reason,
                    "timestamp": datetime.now(),
                    # 개별 진입조건 상태 (스캐너 직관 표기용)
                    "trend_ok": bool(getattr(sig, "trend_ok", False)),
                    "ema_align_ok": bool(getattr(sig, "ema_align_ok", False)),
                    "pullback_ok": bool(getattr(sig, "pullback_ok", False)),
                    "rsi_range_ok": bool(getattr(sig, "rsi_range_ok", False)),
                    "bb_break_ok": bool(getattr(sig, "bb_break_ok", False)),
                    "bb_rsi_ok": bool(getattr(sig, "bb_rsi_ok", False)),
                })

                # 갭 탈출 감지 → 보유 포지션 즉각 청산 콜백
                if getattr(sig, "gap_exit", False) and self.on_gap_exit:
                    self._log_sync(f"[GAP EXIT] {sym} 갭 발생 감지 → 청산 콜백 실행")
                    import inspect
                    if inspect.iscoroutinefunction(self.on_gap_exit):
                        await self.on_gap_exit(sig)
                    else:
                        self.on_gap_exit(sig)

                if sig.direction in ("long", "short"):
                    signal_count += 1
                    self._log_sync(f"[SIG] {sym} {sig.direction.upper()} 신호 포착 (강도 {sig.strength}%)")
                    if self.on_signal:
                        import inspect
                        if inspect.iscoroutinefunction(self.on_signal):
                            await self.on_signal(sig)
                        else:
                            self.on_signal(sig)

                if not was_cached:
                    await asyncio.sleep(0.5)
                else:
                    await asyncio.sleep(0.3)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"종목 스캔 오류 ({sym}): {e}")
                continue

        results.sort(key=lambda x: x["strength"], reverse=True)

        async with self.lock:
            self.scan_results = results
            self.last_scan_time = datetime.now()
            self.scan_count += 1
            
            # --- 추가: UI 스캐너 탭 연동을 위한 파일 저장 ---
            try:
                import json, os
                _fp = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scan_results.json")
                _data = {
                    "last_scan_time": self.last_scan_time.isoformat() if self.last_scan_time else None,
                    "results": results
                }
                with open(_fp, "w", encoding="utf-8") as f:
                    json.dump(_data, f, default=str, ensure_ascii=False)
            except Exception as e:
                self._log_sync(f"[SCANNER] scan_results.json 저장 실패: {e}")
            # -----------------------------------------------

        self._log_sync(
            f"[SCAN] 완료: {len(results)}개 종목 · 신호 {signal_count}개 · "
            f"API 호출 {api_calls}회 · 캐시 히트 {cache_hit}회"
        )

        if self.on_scan_complete:
            try:
                import inspect
                if inspect.iscoroutinefunction(self.on_scan_complete):
                    await self.on_scan_complete()
                else:
                    self.on_scan_complete()
            except Exception as e:
                logger.warning(f"on_scan_complete 콜백 오류: {e}")

    def _log_sync(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self.log_buffer.append(entry)
        if len(self.log_buffer) > 200:
            self.log_buffer = self.log_buffer[-200:]
        logger.info(msg)

    async def get_logs(self, last_n: int = 50) -> List[str]:
        async with self.lock:
            return list(self.log_buffer[-last_n:])

    async def get_results(self) -> List[Dict]:
        async with self.lock:
            return list(self.scan_results)
