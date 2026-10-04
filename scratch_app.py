"""
AI QUANTUM — OKX Auto-Trading Dashboard
Streamlit 기반 전문가용 실시간 대시보드 (Slim Entrypoint)
"""
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from core.exchange import OKXClient
from core.scanner import Scanner
from core.trader import AutoTrader
from core.engine import QuantumEngine, EngineState
from core.config import CFG
import core.stats as stats_store

# Import Tab views and helpers
from ui.settings_tab import sync_p, render_settings
from ui.dashboard_tab import render_dashboard
from ui.scanner_tab import render_scanner
from ui.history_tab import render_history
from ui.entry_tab import render_entry_guide
from core.api_keys import load_api_keys
from core.version import  read_engine_liveness

load_dotenv(override=True)
# [8401] api.md를 OKX 키의 단일 출처로 승격 — 복제 당시 딸려온 구형 .env 키를 덮어씀
load_api_keys(override=True)

# ── 브라우저 없이 자동 엔진 초기화 (백그라운드 스레드) ──────────────
# QuantumEngine 싱글턴의 _initialized 플래그로 중복 실행 방지
# (Streamlit 리런마다 이 코드가 실행되지만, 엔진은 프로세스당 1회만 초기화)
import threading as _threading

def _auto_init_engine():
    """브라우저 없이 백그라운드에서 API 연결 및 스캐너 자동 시작"""
    import time as _time, asyncio as _asyncio
    _time.sleep(0.5)  # [v4.4.3] 초기 대기 시간 최적화: 4초 → 0.5초 (UI 응답성 극대화)
    try:
        _engine = QuantumEngine.get_instance()
        if _engine._initialized:
            return  # 이미 초기화됨 — 중복 방지
        _ak = os.getenv("OKX_API_KEY", "")
        _sk = os.getenv("OKX_SECRET_KEY", "")
        _pw = os.getenv("OKX_PASSPHRASE", "")
        if not _ak or not _sk:
            logger.warning("[AUTO-INIT] .env API 키 없음 — 자동 초기화 건너뜀")
            return
        logger.info("[AUTO-INIT] 백그라운드 엔진 초기화 시작...")
        # 엔진의 asyncio 루프에 초기화 요청
        import asyncio as _asyncio
        future = _asyncio.run_coroutine_threadsafe(
            _engine._initialize_async(_ak, _sk, _pw), _engine._loop
        )
        success, msg = future.result(timeout=15)  # [v4.4.3] 타임아웃 최적화: 30초 → 15초
        if success:
            logger.info(f"[AUTO-INIT] ✅ 초기화 성공: {msg}")
            # [단일 트레이더 일원화] 대시보드 엔진은 모니터·표시 전용 → 실매매(진입)는 bot.py 단독.
            # app 엔진 트레이더는 활성화하지 않고(중복 진입 방지) 스캐너만 가동(스캔 표시·청산 기록).
            # [2026-10-01] app.py에서는 더 이상 백그라운드 스캐너를 돌리지 않습니다.
            logger.info("[AUTO-INIT] 📊 모니터 모드 — 스캐너 표시용 가동 (백그라운드 스캔 비활성화)")
        else:
            logger.error(f"[AUTO-INIT] ❌ 초기화 실패: {msg}")
    except Exception as _e:
        logger.error(f"[AUTO-INIT] 예외: {_e}")

# 엔진이 아직 미초기화 상태일 때만 스레드 시작
_engine_singleton = QuantumEngine.get_instance()
if not _engine_singleton._initialized and not getattr(_engine_singleton, '_auto_init_thread_started', False):
    _engine_singleton._auto_init_thread_started = True
    _threading.Thread(target=_auto_init_engine, daemon=True, name="auto-init").start()
    logger.info("[AUTO-INIT] 백그라운드 초기화 스레드 시작")

# ── 앱 버전 (git tag와 동기화) ─────────────────────────
@st.cache_data(ttl=5)
def get_app_version():
    try:
        import subprocess
        tag = subprocess.check_output(["git", "describe", "--tags", "--abbrev=0"]).strip().decode("utf-8")
        return f"OKX {tag}"
    except Exception:
        return "OKX v2.5.1"

APP_VERSION = get_app_version()

# ── 페이지 설정 ───────────────────────────────────────
st.set_page_config(
    page_title="AI QUANTUM · OKX Trader",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="auto",
)

# ── 보안 로그인 기능 ───────────────────────────────────
# 사용자의 요청에 따라 비밀번호 입력 기능을 삭제하였습니다.

# ── Wall Street Professional Terminal CSS ─────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;700&display=swap');
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');

    /* [전역] 단어 줄바꿈 금지 — 한 단어가 절대 두 라인에 걸쳐 쪼개지지 않도록 */
    *, *::before, *::after {
        word-break: keep-all !important;
        overflow-wrap: normal !important;
        word-wrap: normal !important;
    }

    html {
        /* [폰트 84%] 기존 105% × 0.84 = 88.2% → 모든 rem/%/em 폰트가 원본의 84%로 축소 */
        font-size: 88.2% !important;
    }

    :root {
        --terminal-bg: #030408;
        --terminal-surface: rgba(13, 17, 33, 0.45);
        --terminal-border: rgba(255, 255, 255, 0.08);
        --terminal-text: #e2e8f0;
        --terminal-dim: #718096;
        --terminal-accent: #00e0ff; /* 영롱한 아쿠아 블루 */
        --terminal-accent-glow: rgba(0, 224, 255, 0.15);
        --terminal-green: #10b981;
        --terminal-red: #ef4444;
        --glass-border: rgba(255, 255, 255, 0.06);
    }

    html, body, [data-testid="stAppViewContainer"] {
        background-color: var(--terminal-bg) !important;
        background-image: 
            radial-gradient(circle at 50% 50%, rgba(35, 60, 105, 0.8) 0%, rgba(10, 15, 30, 0.95) 55%, rgba(3, 4, 8, 1) 100%),
            linear-gradient(to right, rgba(255, 255, 255, 0.05) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
        background-size: 100% 100%, 38px 38px, 38px 38px;
        background-attachment: fixed;
        color: var(--terminal-text) !important;
        font-family: 'Pretendard', 'Inter', sans-serif !important;
    }

    [data-testid="stHeader"] { background: transparent !important; }

    [data-testid="stSidebar"] {
        width: 360px !important;
        min-width: 360px !important;
        max-width: 360px !important;
        background-color: rgba(6, 8, 18, 0.85) !important;
        backdrop-filter: blur(20px) !important;
        -webkit-backdrop-filter: blur(20px) !important;
        border-right: 1px solid var(--glass-border) !important;
    }

    /* 메트릭 카드: 글래스모피즘 스타일 적용 */
    [data-testid="metric-container"] {
        background: var(--terminal-surface) !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border: 1px solid var(--glass-border) !important;
        border-radius: 8px !important;
        padding: 12px 18px !important;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3) !important;
        transition: all 0.3s ease;
    }
    [data-testid="metric-container"]:hover {
        border-color: rgba(0, 224, 255, 0.25) !important;
        box-shadow: 0 8px 32px 0 rgba(0, 224, 255, 0.08) !important;
        transform: translateY(-1px);
    }
    [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 1.5rem !important;
        font-weight: 700 !important;
        color: #ffffff !important;
    }
    [data-testid="stMetricLabel"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.85rem !important;
        letter-spacing: 0.08em !important;
        color: #94a3b8 !important;
        text-transform: uppercase !important;
    }

    /* 버튼: 영롱한 네온 느낌 */
    .stButton > button {
        background: rgba(0, 224, 255, 0.03) !important;
        color: var(--terminal-accent) !important;
        border: 1px solid rgba(0, 224, 255, 0.3) !important;
        border-radius: 6px !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
        transition: all 0.25s ease !important;
        box-shadow: 0 2px 8px rgba(0, 224, 255, 0.05) !important;
        height: 38px !important;
        margin-top: 0px !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    .stButton > button:hover {
        background: var(--terminal-accent) !important;
        color: #030408 !important;
        border-color: var(--terminal-accent) !important;
        box-shadow: 0 0 15px rgba(0, 224, 255, 0.3) !important;
    }

    /* 특수 버튼 (새로고침 등) */
    .refresh-btn button {
        border-color: #a78bfa !important;
        color: #a78bfa !important;
        background: rgba(167, 139, 250, 0.03) !important;
    }
    .refresh-btn button:hover {
        background: #a78bfa !important;
        color: #030408 !important;
        box-shadow: 0 0 15px rgba(167, 139, 250, 0.3) !important;
    }

    /* 탭 */
    .stTabs [data-baseweb="tab-list"] {
        background: rgba(10, 14, 28, 0.4) !important;
        border: 1px solid var(--glass-border) !important;
        border-radius: 8px !important;
        padding: 4px !important;
    }
    .stTabs [data-baseweb="tab"] {
        color: #94a3b8 !important;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.9rem !important;
        padding: 8px 16px;
        border-radius: 6px !important;
        transition: all 0.2s;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(0, 224, 255, 0.15) !important;
        color: var(--terminal-accent) !important;
        border: 1px solid rgba(0, 224, 255, 0.35) !important;
        font-weight: 700 !important;
    }

    /* 멀티셀렉트 태그 (버튼) */
    span[data-baseweb="tag"] {
        background-color: #333333 !important;
        color: #e2e8f0 !important;
    }

    /* 인풋 필드 */
    .stTextInput input, .stSelectbox select, .stNumberInput input {
        background: rgba(5, 7, 15, 0.8) !important;
        border: 1px solid var(--glass-border) !important;
        color: var(--terminal-text) !important;
        font-family: 'JetBrains Mono', monospace !important;
        border-radius: 6px !important;
        font-size: 0.9rem !important;
    }
    .stTextInput input:focus, .stSelectbox select:focus, .stNumberInput input:focus {
        border-color: var(--terminal-accent) !important;
        box-shadow: 0 0 8px rgba(0, 224, 255, 0.2) !important;
    }

    /* 멀티셀렉트 태그(칩) 색상 (빨강 -> 다크그레이) */
    span[data-baseweb="tag"] {
        background-color: #374151 !important;
        color: #f8fafc !important;
    }

    /* 토글/체크박스 라벨 글자 색상 흰색 강제 적용 */
    div[data-testid="stCheckbox"] label,
    div[data-testid="stCheckbox"] span,
    div[data-testid="stCheckbox"] p {
        color: #ffffff !important;
    }

    /* 툴팁 (물음표) 아이콘 가시성 개선 (흰색) */
    div[data-testid="stTooltipIcon"] svg,
    div[data-testid="stTooltipIcon"] button,
    div[data-testid="stTooltipIcon"] {
        color: #ffffff !important;
        fill: #ffffff !important;
        opacity: 1 !important;
    }

    /* 사이드바 포함 툴팁 문구 폰트 크기 통일 (12px) */
    [role="tooltip"],
    div[data-baseweb="popover"] [data-baseweb="tooltip"],
    div[data-baseweb="tooltip"],
    .cooldown-hover-tip {
        font-size: 10.08px !important;
    }

    /* 데이터프레임 */
    [data-testid="stDataFrame"] {
        border: 1px solid var(--glass-border) !important;
        border-radius: 8px !important;
        background: rgba(10, 14, 28, 0.3) !important;
    }

    /* 로고: 우상향 심볼(↗) 및 영롱한 오로라 그라데이션 */
    .quantum-logo {
        font-family: 'Pretendard', 'Inter', sans-serif;
        font-size: calc(1.1rem * 1.55);
        font-weight: 800;
        color: var(--terminal-text);
        border-bottom: 1px solid var(--glass-border);
        padding-bottom: 12px;
        margin-bottom: 20px;
        position: relative;
    }

    @keyframes aurora-flow {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    .rainbow-text {
        font-family: 'Pretendard', 'Inter', sans-serif !important;
        background: linear-gradient(135deg, #00f0ff, #8b5cf6, #ec4899, #00f0ff);
        background-size: 300% 300%;
        -webkit-background-clip: text !important;
        -webkit-text-fill-color: transparent !important;
        background-clip: text !important;
        color: transparent !important;
        font-weight: 900 !important;
        animation: aurora-flow 6s ease infinite;
        text-shadow: 0 0 20px rgba(0, 224, 255, 0.1);
    }

    /* 공통 버튼 스타일의 헤더 배지 */
    .header-elapsed-row {
        display: flex !important;
        align-items: center !important;
        gap: 18px !important;
        height: 38px !important;
        flex-wrap: nowrap !important;
    }
    .elapsed-since {
        display: inline-flex !important;
        align-items: center !important;
        color: #e2e8f0 !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 1.6rem !important;
        font-weight: 800 !important;
        letter-spacing: 1px !important;
        white-space: nowrap !important;
    }
    .idle-since {
        display: inline-flex !important;
        align-items: center !important;
        color: #facc15 !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 1.15rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.5px !important;
        white-space: nowrap !important;
    }

    .header-btn-like {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: 100% !important;
        height: 38px !important;
        background: rgba(13, 17, 33, 0.4) !important;
        border: 1px solid var(--glass-border) !important;
        color: #94a3b8 !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.9rem !important;
        font-weight: 600 !important;
        text-align: center !important;
        box-sizing: border-box !important;
        border-radius: 6px !important;
        white-space: nowrap !important;
    }

    @keyframes live-blink-sideways {
        0%   { opacity: 1;   box-shadow: inset 0 0 15px rgba(16,185,129,0.4), 0 0 15px rgba(16,185,129,0.6); border-color: rgba(16,185,129,0.8); }
        50%  { opacity: 0.6; box-shadow: inset 0 0 5px rgba(16,185,129,0.1),  0 0 5px rgba(16,185,129,0.2);  border-color: rgba(16,185,129,0.3); }
        100% { opacity: 1;   box-shadow: inset 0 0 15px rgba(16,185,129,0.4), 0 0 15px rgba(16,185,129,0.6); border-color: rgba(16,185,129,0.8); }
    }
    @keyframes live-blink-bull {
        0%   { opacity: 1;   box-shadow: inset 0 0 15px rgba(239,68,68,0.4),  0 0 15px rgba(239,68,68,0.7);  border-color: rgba(239,68,68,0.9); }
        50%  { opacity: 0.5; box-shadow: inset 0 0 5px rgba(239,68,68,0.1),   0 0 5px rgba(239,68,68,0.2);   border-color: rgba(239,68,68,0.3); }
        100% { opacity: 1;   box-shadow: inset 0 0 15px rgba(239,68,68,0.4),  0 0 15px rgba(239,68,68,0.7);  border-color: rgba(239,68,68,0.9); }
    }
    @keyframes live-blink-bear {
        0%   { opacity: 1;   box-shadow: inset 0 0 15px rgba(59,130,246,0.4), 0 0 15px rgba(59,130,246,0.7); border-color: rgba(59,130,246,0.9); }
        50%  { opacity: 0.5; box-shadow: inset 0 0 5px rgba(59,130,246,0.1),  0 0 5px rgba(59,130,246,0.2);  border-color: rgba(59,130,246,0.3); }
        100% { opacity: 1;   box-shadow: inset 0 0 15px rgba(59,130,246,0.4), 0 0 15px rgba(59,130,246,0.7); border-color: rgba(59,130,246,0.9); }
    }

    .header-badge-live {
        border-color: rgba(16,185,129,0.8) !important;
        color: #10b981 !important;
        font-weight: 800 !important;
        background: rgba(16,185,129,0.15) !important;
        animation: live-blink-sideways 1.2s infinite ease-in-out !important;
        position: relative !important;
    }
    .header-badge-live .dot {
        width: 8px; height: 8px;
        background: #10b981 !important;
        border-radius: 50% !important;
        margin-right: 8px !important;
        display: inline-block !important;
        box-shadow: 0 0 6px #10b981;
    }
    .header-badge-live-bull {
        border-color: rgba(239,68,68,0.9) !important;
        color: #ef4444 !important;
        font-weight: 800 !important;
        background: rgba(239,68,68,0.12) !important;
        animation: live-blink-bull 1.0s infinite ease-in-out !important;
        position: relative !important;
    }
    .header-badge-live-bull .dot {
        width: 8px; height: 8px;
        background: #ef4444 !important;
        border-radius: 50% !important;
        margin-right: 8px !important;
        display: inline-block !important;
        box-shadow: 0 0 8px #ef4444;
    }
    .header-badge-live-bear {
        border-color: rgba(59,130,246,0.9) !important;
        color: #3b82f6 !important;
        font-weight: 800 !important;
        background: rgba(59,130,246,0.12) !important;
        animation: live-blink-bear 1.0s infinite ease-in-out !important;
        position: relative !important;
    }
    .header-badge-live-bear .dot {
        width: 8px; height: 8px;
        background: #3b82f6 !important;
        border-radius: 50% !important;
        margin-right: 8px !important;
        display: inline-block !important;
        box-shadow: 0 0 8px #3b82f6;
    }
    .live-badge-wrap {
        position: relative;
        display: inline-block;
        width: 100%;
    }
    .live-badge-wrap .live-tooltip {
        visibility: hidden;
        opacity: 0;
        background: rgba(10,15,28,0.97);
        border: 1px solid rgba(100,116,139,0.5);
        border-radius: 8px;
        color: #e2e8f0;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10.92px;
        line-height: 1.6;
        padding: 10px 14px;
        position: absolute;
        top: calc(100% + 8px);
        right: 0;
        min-width: 260px;
        z-index: 9999;
        box-shadow: 0 8px 32px rgba(0,0,0,0.6);
        transition: opacity 0.2s ease, visibility 0.2s ease;
        pointer-events: none;
        white-space: pre-line;
    }
    .live-badge-wrap:hover .live-tooltip {
        visibility: visible;
        opacity: 1;
    }
    .header-badge-stopped {
        border-color: rgba(239,68,68,0.4) !important;
        color: var(--terminal-red) !important;
        background: rgba(239,68,68,0.08) !important;
    }
    .header-badge-stopped .dot {
        width: 8px; height: 8px;
        background: var(--terminal-red) !important;
        border-radius: 50% !important;
        margin-right: 8px !important;
        display: inline-block !important;
        box-shadow: 0 0 6px var(--terminal-red);
    }

    /* 시스템 로그 박스 */
    .log-box {
        background: rgba(5, 7, 15, 0.85);
        border: 1px solid var(--glass-border);
        border-radius: 8px;
        padding: 12px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.9rem;
        color: #cbd5e1;
        height: 250px;
        overflow-y: auto;
        line-height: 1.5;
        white-space: pre-wrap;
    }
    @keyframes log-yellow-blink {
        0% { opacity: 1; }
        50% { opacity: 0.6; }
        100% { opacity: 1; }
    }
    .log-latest {
        color: #f59e0b !important;
        font-weight: bold;
        background: rgba(245, 158, 11, 0.06) !important;
        border-left: 3px solid #f59e0b;
        padding: 2px 8px;
        animation: log-yellow-blink 1.5s infinite ease-in-out;
    }

    /* 구분선 */
    hr { border-color: var(--glass-border) !important; margin: 15px 0 !important; }

    /* Wall Street Metric Bar */
    .metric-bar-container {
        display: flex;
        justify-content: space-between;
        background: rgba(13, 17, 33, 0.35);
        border: 1px solid var(--glass-border);
        border-radius: 8px;
        padding: 12px 0;
        margin-bottom: 20px;
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
    }
    .terminal-metric-item {
        flex: 1;
        border-right: 1px solid var(--glass-border);
        padding: 0 20px;
        transition: all 0.3s ease;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
    }
    .terminal-metric-item:last-child { border-right: none; }
    .terminal-metric-item:hover {
        background: rgba(255, 255, 255, 0.02);
    }
    .terminal-metric-label {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.85rem;
        color: #94a3b8;
        text-transform: uppercase;
        margin-bottom: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* 커스텀 금융 터미널 툴팁 */
    .terminal-tooltip {
        position: relative;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        cursor: help;
        color: var(--terminal-accent);
        font-weight: bold;
        margin-left: 6px;
        font-size: 0.8rem;
        background: rgba(0, 224, 255, 0.1);
        border: 1px solid rgba(0, 224, 255, 0.3);
        width: 16px;
        height: 16px;
        border-radius: 4px;
    }
    .terminal-tooltip .tooltip-text {
        visibility: hidden;
        width: 330px;
        background-color: #0b0f19 !important;
        color: #ffffff !important;
        text-align: left !important;
        line-height: 1.5 !important;
        border: 1px solid rgba(0, 224, 255, 0.4) !important;
        border-radius: 6px !important;
        padding: 12px 16px !important;
        position: absolute;
        z-index: 9999 !important;
        bottom: 125%;
        left: 50%;
        transform: translateX(-50%);
        opacity: 0;
        transition: opacity 0.2s;
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.8rem !important;
        font-weight: normal !important;
        text-transform: none !important;
        box-shadow: 0px 8px 24px rgba(0, 0, 0, 0.5) !important;
    }
    .terminal-tooltip:hover .tooltip-text {
        visibility: visible;
        opacity: 1;
    }
    .terminal-metric-value {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.3rem;
        font-weight: 700;
        color: #ffffff;
        line-height: 1.1;
        text-align: center;
    }
    .terminal-metric-sub {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.85rem;
        margin-top: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
    }

    /* 청산 버튼 특화 (최소 14px 준수, 글래스모피즘 스타일 조화) */
    .small-btn-marker + div.stButton button,
    .small-btn-marker + div[data-testid="stButton"] button,
    div.small-btn-marker ~ div.stButton button {
        font-size: 11.76px !important;
        height: 28px !important;
        min-height: 28px !important;
        line-height: 1 !important;
        padding: 0 10px !important;
        border-color: var(--terminal-red) !important;
        color: var(--terminal-red) !important;
        border-radius: 6px !important;
        background: rgba(239, 68, 68, 0.05) !important;
        margin-top: -12px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        transition: all 0.2s ease !important;
    }
    .small-btn-marker + div.stButton button:hover,
    .small-btn-marker + div[data-testid="stButton"] button:hover {
        background: var(--terminal-red) !important;
        color: white !important;
        box-shadow: 0 0 10px rgba(239, 68, 68, 0.4) !important;
    }

    /* 깜빡임 애니메이션 (터미널 스타일) */
    @keyframes terminal-blink {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }
    .badge-pink-blink, .badge-green-blink, .badge-red-blink {
        border-radius: 4px !important;
        animation: terminal-blink 1.2s infinite ease-in-out;
    }
    /* Streamlit Metric Delta Color Override (Profit: Red, Loss: Blue) */
    [data-testid="stMetricDelta"] > div {
        color: #ef4444 !important;
    }
    [data-testid="stMetricDelta"] > div:has(svg[data-testid="stMetricDeltaIconDown"]) {
        color: #3b82f6 !important;
    }
    [data-testid="stMetricDelta"] > div[style*="color: rgb(9, 171,  green)"],
    [data-testid="stMetricDelta"] > div[style*="color: #09ab3b"] {
        color: #ef4444 !important;
    }
    [data-testid="stMetricDelta"] > div[style*="color: rgb(255, 43, 43)"],
    [data-testid="stMetricDelta"] > div[style*="color: #ff2b2b"] {
        color: #3b82f6 !important;
    }

    /* 탭바와 헤더 배지 수평 정렬 */
    @media (min-width: 1024px) {
        .floating-header-wrapper + div[data-testid="stHorizontalBlock"] {
            margin-bottom: -46px !important;
            position: relative !important;
            z-index: 9999 !important;
            top: 4px !important;
        }
        .stTabs [data-baseweb="tab-list"] {
            max-width: 55% !important;
        }
    }

    .stTabs [data-baseweb="tab-list"] {
        overflow: visible !important;
    }
    .stTabs button[data-baseweb="tab"] {
        position: relative;
        overflow: visible !important;
    }
    .stTabs button[data-baseweb="tab"]::after {
        position: absolute;
        bottom: 125%;
        left: 50%;
        transform: translateX(-50%);
        background-color: #0b0f19 !important;
        color: #ffffff !important;
        border: 1px solid rgba(0, 224, 255, 0.4) !important;
        border-radius: 6px !important;
        padding: 6px 12px !important;
        font-family: 'Pretendard', sans-serif !important;
        font-size: 0.8rem !important;
        font-weight: normal !important;
        white-space: nowrap;
        z-index: 999999 !important;
        box-shadow: 0px 8px 24px rgba(0, 0, 0, 0.5) !important;
        opacity: 0;
        visibility: hidden;
        transition: opacity 0.2s, visibility 0.2s;
        pointer-events: none;
    }
    .stTabs button[data-baseweb="tab"]:hover::after {
        opacity: 1;
        visibility: visible;
    }

    /* 탭별 개별 툴팁 텍스트 바인딩 */
    .stTabs button[data-baseweb="tab"]:nth-child(1)::after {
        content: "실시간 잔고, 미실현 손익 및 활성 포지션 모니터링";
    }
    .stTabs button[data-baseweb="tab"]:nth-child(2)::after {
        content: "전략 부합 종목 실시간 발굴 및 탐지 상태 모니터링";
    }
    .stTabs button[data-baseweb="tab"]:nth-child(3)::after {
        content: "거래소 체결 이력 조회 및 로컬 CSV 기반 성적 분석";
    }
    .stTabs button[data-baseweb="tab"]:nth-child(4)::after {
        content: "롱/숏 포지션 진입 상세 조건 및 전략 로직 가이드";
    }
    .stTabs button[data-baseweb="tab"]:nth-child(5)::after {
        content: "레버리지, 증거금, 손익절 및 기술 지표 파라미터 설정";
    }
    
    [data-testid="stHorizontalBlock"] div[data-testid="stButton"] {
        margin-top: 0px !important;
        display: flex;
        align-items: center;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 사이드바 너비를 브라우저 localStorage에 저장/복원
components.html(
    """
    <script>
    (function () {
        const KEY = "aq_sidebar_width_px";
        const MIN_W = 240;
        const MAX_W = 760;

        function clamp(v) {
            return Math.max(MIN_W, Math.min(MAX_W, v));
        }

        function applySavedWidth(sidebar) {
            const raw = window.localStorage.getItem(KEY);
            let w = 360;
            if (raw) {
                const parsed = parseInt(raw, 10);
                if (Number.isFinite(parsed)) w = clamp(parsed);
            }
            sidebar.style.width = w + "px";
            sidebar.style.minWidth = w + "px";
            sidebar.style.maxWidth = w + "px";
        }

        function start() {
            const doc = window.parent.document || document;
            const sidebar = doc.querySelector("[data-testid='stSidebar']");
            if (!sidebar) return;

            applySavedWidth(sidebar);

            if (sidebar.__aqSidebarObserverAttached) return;
            sidebar.__aqSidebarObserverAttached = true;

            const obs = new ResizeObserver(function (entries) {
                for (const e of entries) {
                    const w = Math.round(e.contentRect.width || 0);
                    if (!w) continue;
                    if (w < MIN_W || w > MAX_W) continue;
                    window.localStorage.setItem(KEY, String(w));
                }
            });
            obs.observe(sidebar);
        }

        setTimeout(start, 80);
        setTimeout(start, 600);
    })();
    </script>
    """,
    height=0,
)

def init_session():
    # --- [UI Config Sync Patch] 실시간 설정 파일 동기화 ---
    try:
        from core.config import load_config, CFG
        new_cfg = load_config()
        for k, v in new_cfg.__dict__.items():
            setattr(CFG, k, v)
        engine = QuantumEngine.get_instance()
        engine.cfg = new_cfg
        
        # UI Checkbox 캐시 동기화
        if "bluefrog_mode" in st.session_state:
            st.session_state.bluefrog_mode = getattr(CFG, "USE_BLUEFROG", True)
        if "auto_switch_mode" in st.session_state:
            st.session_state.auto_switch_mode = getattr(CFG, "USE_AUTO_MODE_SWITCH", True)
    except Exception as e:
        pass
    # ----------------------------------------------------
    engine = QuantumEngine.get_instance()
    is_trading = getattr(CFG, "AUTO_TRADING", False)

    defaults = {
        "engine": engine,
        "api_connected": engine.is_ready,
        "auto_trading": is_trading,
        "bluefrog_mode": getattr(CFG, "USE_BLUEFROG", True),
        "auto_switch_mode": getattr(CFG, "USE_AUTO_MODE_SWITCH", True),
        "rsi_auto_switch": CFG.USE_RSI_FILTER,
        "active_preset": "기본 (Stable)",
        "closing_symbols": {},
        "sb_use_auto_compound": getattr(CFG, "USE_AUTO_COMPOUND", False),
        "main_use_auto_compound": getattr(CFG, "USE_AUTO_COMPOUND", False),
        "sb_auto_compound_pct": float(getattr(CFG, "AUTO_COMPOUND_PCT", 18.0)),
        "main_auto_compound_pct": float(getattr(CFG, "AUTO_COMPOUND_PCT", 18.0)),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    if not hasattr(engine, "closing_symbols"):
        engine.closing_symbols = {}
    st.session_state.closing_symbols = engine.closing_symbols

    for state_key, env_keys in [("api_key_input", ["OKX_API_KEY"]), 
                                ("secret_input", ["OKX_SECRET_KEY"]), 
                                ("pass_input", ["OKX_PASSPHRASE"]),
                                ("settings_telegram_token", ["TELEGRAM_BOT_TOKEN"]),
                                ("settings_telegram_chat_id", ["TELEGRAM_CHAT_ID"])]:
        env_val = ""
        for k in env_keys:
            env_val = os.getenv(k, "")
            if env_val:
                break
        if env_val and (state_key not in st.session_state or not st.session_state[state_key]):
            st.session_state[state_key] = env_val

def connect_api(api_key, secret_key, passphrase):
    if not api_key or not secret_key:
        return False, "❌ API 키를 모두 입력해주세요."
    
    engine: QuantumEngine = st.session_state.engine
    success, msg = engine.initialize(api_key, secret_key, passphrase)
    
    if success:
        st.session_state.api_connected = True
        try:
            engine.sync_trades_to_csv()
        except Exception:
            pass
        return True, msg
    return False, msg

init_session()

# [8405 이식] 앱 시작 시간 기록(세션 1회) — 무진입/무포지션 기준 fallback
if "_app_start_time" not in st.session_state:
    st.session_state._app_start_time = datetime.utcnow() + timedelta(hours=9)

if not st.session_state.api_connected:
    ak = os.getenv("OKX_API_KEY", "")
    sk = os.getenv("OKX_SECRET_KEY", "")
    pw = os.getenv("OKX_PASSPHRASE", "")
    if ak and sk:
        connect_api(ak, sk, pw)

dash = None
if st.session_state.api_connected:
    try:
        engine: QuantumEngine = st.session_state.engine
        dash = engine.get_dashboard_data()
    except Exception:
        pass

# ══════════════════════════════════════════════════════
# 사이드바 — API 설정
# ══════════════════════════════════════════════════════
with st.sidebar:
    # SINCE 시각 = '수익률,승률 초기화' 버튼 마지막 클릭 시각 (perf_start_time)
    _perf_start = stats_store.load_stats().get("perf_start_time", "2026-07-05 15:54:00")
    try:
        _d, _t = _perf_start.split(" ")
        _since_disp = _d.replace("-", ".") + " " + _t[:5]
    except Exception:
        _since_disp = "2026.05.27 22:06"
    st.markdown(
        '<div class="quantum-logo" style="letter-spacing:-0.5px;" '
        'title="[TTM Squeeze + 200 EMA 전략]&#10;'
        '1. 200 EMA 필터: 장기 추세 방향성 확인 (Long: 가격 > 200 EMA, Short: 가격 < 200 EMA)&#10;'
        '2. TTM Squeeze 돌파: 볼린저 밴드와 켈트너 채널의 변동성 돌파 감지 (Squeeze OFF 시 진입)&#10;'
        '3. 모멘텀 및 캔들 색상 필터: 선행 추세 확증 (Momentum 히스토그램 및 캔들 색상 일치)&#10;'
        '4. RSI 필터: 과열권 진입 제한 및 추격 매매 노이즈 필터링">'
        f'<span style="color:#ffffff; font-size: 100%;">8401_<span style="color:blue;">BlueFrog</span></span><br><span style="font-size:15px; color:#888; font-family:\'JetBrains Mono\', monospace;">SINCE {_since_disp}</span><br><span style="font-size:11px; color:#4ade80; font-weight:700;">🚀 5대 퀀트 수익성부스터 ACTIVE</span></div>',
        unsafe_allow_html=True,
    )

    st.markdown("---")
    
    # 사이드바 타임프레임 동적 변경 UI (인메모리 CFG 연동 방식)
    current_tf = getattr(CFG, "TIMEFRAME", "4h")
    tf_options = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]
    try:
        tf_idx = tf_options.index(current_tf)
    except ValueError:
        tf_idx = 7  # default to 4h
    
    selected_tf = st.selectbox("⏱️ 타임프레임", tf_options, index=tf_idx, key="sidebar_tf_select")
    if selected_tf != current_tf:
        from core.config import save_config
        try:
            CFG.TIMEFRAME = selected_tf
            save_config(CFG)
            st.rerun()
        except Exception as e:
            st.error(f"설정 저장 실패: {e}")

    # [2026-09-03] 최대 보유 티커수 — 타임프레임 바로 아래. 같은 즉시반영 방식.
    current_maxpos = int(getattr(CFG, "MAX_POSITIONS", 3) or 3)
    selected_maxpos = st.number_input(
        "📊 최대 보유 티커수", min_value=1, max_value=20,
        value=current_maxpos, step=1, key="sidebar_maxpos_input",
        help="동시에 들고 갈 수 있는 최대 종목 수입니다. "
             "1회 진입 증거금 × 이 값이 잔고를 넘지 않도록 잡으세요.",
    )
    if int(selected_maxpos) != current_maxpos:
        from core.config import save_config
        try:
            CFG.MAX_POSITIONS = int(selected_maxpos)
            save_config(CFG)
            st.rerun()
        except Exception as e:
            st.error(f"설정 저장 실패: {e}")

    st.markdown("---")

    api_key = st.text_input(
        "🔑 API Key", type="password", key="api_key_input"
    )
    secret_key = st.text_input(
        "🔑 Secret Key", type="password", key="secret_input"
    )
    passphrase = st.text_input(
        "🔑 Passphrase", type="password", key="pass_input"
    )

    if st.button("🔗  OKX 연결", use_container_width=True):
        with st.spinner("연결 중..."):
            ak = api_key if api_key else os.getenv("OKX_API_KEY", "")
            sk = secret_key if secret_key else os.getenv("OKX_SECRET_KEY", "")
            pw = passphrase if passphrase else os.getenv("OKX_PASSPHRASE", "")
            success, msg = connect_api(ak, sk, pw)
            if success:
                st.success(msg)
                try:
                    from dotenv import set_key
                    env_path = ".env"
                    if not os.path.exists(env_path):
                        open(env_path, "w").close()
                    if api_key: set_key(env_path, "OKX_API_KEY", api_key)
                    if secret_key: set_key(env_path, "OKX_SECRET_KEY", secret_key)
                    if passphrase: set_key(env_path, "OKX_PASSPHRASE", passphrase)
                except Exception as e:
                    st.warning(f"키 저장 실패: {e}")
            else:
                st.error(msg)

    st.markdown("---")

    auto = st.toggle(
        "🤖 자동매매 가동 (ON/OFF)",
        value=st.session_state.auto_trading,
        help="ON: 실시간 마켓 스캐너 및 자동 매매 엔진을 기동하여 TTM Squeeze + 200 EMA 전략 조건 충족 시 포지션을 자동으로 진입/청산합니다. / OFF: 실시간 스캔을 즉시 중단하고 신규 자동 진입을 차단합니다. (기존 보유 포지션은 유지됩니다)"
    )

    engine: QuantumEngine = st.session_state.engine
    
    # [단일 트레이더 일원화] 실매매(진입)는 bot.py 단독. 토글은 config.json에 기록 →
    # bot.py가 폴링하여 실제 ON/OFF. 대시보드 엔진은 진입하지 않고(중복 진입 방지)
    # 스캐너만 모니터·표시·청산기록용으로 상시 가동한다.
    if auto != st.session_state.auto_trading:
        st.session_state.auto_trading = auto
        CFG.AUTO_TRADING = auto
        CFG.save_settings()   # ← bot.py가 폴링하여 실매매 ON/OFF
        if auto:
            st.toast("🤖 자동매매가 가동(ON) 되었습니다. (실매매: bot.py)")
        else:
            st.toast("⏹️ 자동매매가 중지(OFF) 되었습니다. (실매매: bot.py)")

    bluefrog = st.toggle(
        "🐸 청개구리 모드 (역매매)",
        value=st.session_state.bluefrog_mode,
        help="ON: 청개구리 모드 (롱 신호 ➡️ 숏 진입, 숏 신호 ➡️ 롱 진입)\nOFF: 정방향 모드 (롱 신호 ➡️ 롱 진입, 숏 신호 ➡️ 숏 진입)"
    )

    if bluefrog != st.session_state.bluefrog_mode:
        st.session_state.bluefrog_mode = bluefrog
        CFG.USE_BLUEFROG = bluefrog
        CFG.save_settings()   # ← bot.py가 폴링하여 실매매 모드 반영
        if bluefrog:
            st.toast("🐸 청개구리 모드(역매매)가 가동되었습니다. (롱➡️숏 / 숏➡️롱)")
        else:
            st.toast("🎯 정방향 매매 모드가 가동되었습니다. (롱➡️롱 / 숏➡️숏)")

    auto_switch = st.toggle(
        "⚡ 적응형 매매방향 자동반전 (초기 3~4전 / 5전 3패)",
        value=st.session_state.get("auto_switch_mode", getattr(CFG, "USE_AUTO_MODE_SWITCH", True)),
        help="초기화 직후 3~4회 중 3패(xxx, xxxO, xxOx, xOxx) 또는 최근 청산 5건 중 3건 이상 손실 시 매매 방향(정방향 ↔ 청개구리 모드)을 자동으로 반전 스위칭합니다."
    )

    if auto_switch != st.session_state.get("auto_switch_mode"):
        st.session_state.auto_switch_mode = auto_switch
        CFG.USE_AUTO_MODE_SWITCH = auto_switch
        CFG.save_settings()
        if auto_switch:
            st.toast("⚡ 적응형 매매방향 자동반전이 활성화되었습니다. (초기 3~4전 / 5전 3패 감지 시 모드 반전)")
        else:
            st.toast("⏸️ 자동반전 기능이 해제되었습니다.")

    if engine.is_ready:
        # 대시보드 엔진 트레이더는 항상 비활성 — 진입은 bot.py만 수행
        if engine.trader and engine.trader.enabled:
            engine.disable_trading()
        # 스캐너는 표시·청산기록용으로 상시 가동
        if engine.scanner and not engine.scanner.is_running:
            # engine.start_scanner()  # [2026-10-01] app.py 내 스캐너 구동 중단

    st.session_state.rsi_auto_switch = CFG.USE_RSI_FILTER

    # ── [다중기간 연동 변수값 자동설정] Deep Learning 최적 파라미터 프리셋 ──
    MULTI_PERIOD_PRESETS = {
        "30일 (30d)": {
            "LEVERAGE": 20, "MARGIN_USDT": 18.3, "MAX_POSITIONS": 5,
            "STOP_LOSS_PCT": 0.0396, "TAKE_PROFIT_PCT": 0.0341,
            "TRAILING_ACTIVATE_PCT": 0.0375, "TRAILING_CALLBACK_PCT": 0.0051,
            "MAX_DRAWDOWN_PCT": 0.215, "ALLOW_LONG": True, "ALLOW_SHORT": True,
            "TIMEFRAME": "4h", "SCAN_INTERVAL_SEC": 60, "MIN_VOLUME_USDT": 2_000_000.0,
            "EMA_PERIOD": 102, "BB_PERIOD": 37, "BB_STD": 2.07,
            "RSI_PERIOD": 8, "RSI_OVERSOLD": 25.2, "RSI_OVERBOUGHT": 69.0,
        },
        "15일 (15d)": {
            "LEVERAGE": 20, "MARGIN_USDT": 19.5, "MAX_POSITIONS": 3,
            "STOP_LOSS_PCT": 0.0391, "TAKE_PROFIT_PCT": 0.0458,
            "TRAILING_ACTIVATE_PCT": 0.0427, "TRAILING_CALLBACK_PCT": 0.0019,
            "MAX_DRAWDOWN_PCT": 0.218, "ALLOW_LONG": True, "ALLOW_SHORT": True,
            "TIMEFRAME": "4h", "SCAN_INTERVAL_SEC": 30, "MIN_VOLUME_USDT": 5_000_000.0,
            "EMA_PERIOD": 220, "BB_PERIOD": 26, "BB_STD": 1.74,
            "RSI_PERIOD": 18, "RSI_OVERSOLD": 27.8, "RSI_OVERBOUGHT": 70.5,
        },
        "7일 (7d)": {
            "LEVERAGE": 20, "MARGIN_USDT": 19.8, "MAX_POSITIONS": 5,
            "STOP_LOSS_PCT": 0.0365, "TAKE_PROFIT_PCT": 0.0641,
            "TRAILING_ACTIVATE_PCT": 0.0244, "TRAILING_CALLBACK_PCT": 0.0068,
            "MAX_DRAWDOWN_PCT": 0.277, "ALLOW_LONG": True, "ALLOW_SHORT": False,
            "TIMEFRAME": "4h", "SCAN_INTERVAL_SEC": 20, "MIN_VOLUME_USDT": 5_000_000.0,
            "EMA_PERIOD": 241, "BB_PERIOD": 27, "BB_STD": 1.40,
            "RSI_PERIOD": 16, "RSI_OVERSOLD": 41.6, "RSI_OVERBOUGHT": 74.4,
        },
        "48시간 (48h)": {
            "LEVERAGE": 20, "MARGIN_USDT": 18.8, "MAX_POSITIONS": 6,
            "STOP_LOSS_PCT": 0.0359, "TAKE_PROFIT_PCT": 0.0585,
            "TRAILING_ACTIVATE_PCT": 0.0554, "TRAILING_CALLBACK_PCT": 0.0054,
            "MAX_DRAWDOWN_PCT": 0.205, "ALLOW_LONG": True, "ALLOW_SHORT": False,
            "TIMEFRAME": "15m", "SCAN_INTERVAL_SEC": 10, "MIN_VOLUME_USDT": 5_000_000.0,
            "EMA_PERIOD": 139, "BB_PERIOD": 31, "BB_STD": 1.57,
            "RSI_PERIOD": 13, "RSI_OVERSOLD": 37.4, "RSI_OVERBOUGHT": 67.9,
        },
        "24시간 (24h)": {
            "LEVERAGE": 20, "MARGIN_USDT": 15.1, "MAX_POSITIONS": 5,
            "STOP_LOSS_PCT": 0.0341, "TAKE_PROFIT_PCT": 0.0624,
            "TRAILING_ACTIVATE_PCT": 0.0143, "TRAILING_CALLBACK_PCT": 0.0017,
            "MAX_DRAWDOWN_PCT": 0.119, "ALLOW_LONG": True, "ALLOW_SHORT": False,
            "TIMEFRAME": "15m", "SCAN_INTERVAL_SEC": 10, "MIN_VOLUME_USDT": 2_000_000.0,
            "EMA_PERIOD": 144, "BB_PERIOD": 17, "BB_STD": 2.49,
            "RSI_PERIOD": 20, "RSI_OVERSOLD": 33.7, "RSI_OVERBOUGHT": 58.0,
        },
        "12시간 (12h)": {
            "LEVERAGE": 20, "MARGIN_USDT": 19.2, "MAX_POSITIONS": 4,
            "STOP_LOSS_PCT": 0.0371, "TAKE_PROFIT_PCT": 0.0509,
            "TRAILING_ACTIVATE_PCT": 0.0454, "TRAILING_CALLBACK_PCT": 0.0014,
            "MAX_DRAWDOWN_PCT": 0.199, "ALLOW_LONG": True, "ALLOW_SHORT": False,
            "TIMEFRAME": "1h", "SCAN_INTERVAL_SEC": 60, "MIN_VOLUME_USDT": 10_000_000.0,
            "EMA_PERIOD": 122, "BB_PERIOD": 34, "BB_STD": 2.09,
            "RSI_PERIOD": 9, "RSI_OVERSOLD": 30.0, "RSI_OVERBOUGHT": 72.0,
        },
    }

    PKL_PATH = "scratch/multi_period_results.pkl"
    if os.path.exists(PKL_PATH):
        try:
            import pickle
            with open(PKL_PATH, "rb") as f:
                saved_results = pickle.load(f)
                REQUIRED_19_KEYS = [
                    "LEVERAGE", "MARGIN_USDT", "MAX_POSITIONS",
                    "STOP_LOSS_PCT", "TAKE_PROFIT_PCT",
                    "TRAILING_ACTIVATE_PCT", "TRAILING_CALLBACK_PCT",
                    "MAX_DRAWDOWN_PCT", "ALLOW_LONG", "ALLOW_SHORT",
                    "TIMEFRAME", "SCAN_INTERVAL_SEC", "MIN_VOLUME_USDT",
                    "EMA_PERIOD", "BB_PERIOD", "BB_STD",
                    "RSI_PERIOD", "RSI_OVERSOLD", "RSI_OVERBOUGHT",
                ]
                TYPE_MAP = {
                    "LEVERAGE": int, "MARGIN_USDT": float, "MAX_POSITIONS": int,
                    "STOP_LOSS_PCT": float, "TAKE_PROFIT_PCT": float,
                    "TRAILING_ACTIVATE_PCT": float, "TRAILING_CALLBACK_PCT": float,
                    "MAX_DRAWDOWN_PCT": float, "ALLOW_LONG": bool, "ALLOW_SHORT": bool,
                    "TIMEFRAME": str, "SCAN_INTERVAL_SEC": int, "MIN_VOLUME_USDT": float,
                    "EMA_PERIOD": int, "BB_PERIOD": int, "BB_STD": float,
                    "RSI_PERIOD": int, "RSI_OVERSOLD": float, "RSI_OVERBOUGHT": float,
                }
                for p_name, data in saved_results.items():
                    if p_name in MULTI_PERIOD_PRESETS and "params" in data:
                        p_val = data["params"]
                        if all(k in p_val for k in REQUIRED_19_KEYS):
                            casted_preset = {}
                            for k, t in TYPE_MAP.items():
                                casted_preset[k] = t(p_val[k])
                            MULTI_PERIOD_PRESETS[p_name] = casted_preset
        except Exception:
            pass

    def apply_multi_period_preset():
        selected = st.session_state.get("multi_period_select", "-- 기간을 선택하세요 --")
        if selected == "-- 기간을 선택하세요 --":
            return
        preset = MULTI_PERIOD_PRESETS.get(selected)
        if not preset:
            return

        CFG.LEVERAGE = preset["LEVERAGE"]
        CFG.MARGIN_USDT = preset["MARGIN_USDT"]
        CFG.MAX_POSITIONS = preset["MAX_POSITIONS"]
        CFG.STOP_LOSS_PCT = preset["STOP_LOSS_PCT"]
        CFG.TAKE_PROFIT_PCT = preset["TAKE_PROFIT_PCT"]
        CFG.TRAILING_ACTIVATE_PCT = preset["TRAILING_ACTIVATE_PCT"]
        CFG.TRAILING_CALLBACK_PCT = preset["TRAILING_CALLBACK_PCT"]
        CFG.MAX_DRAWDOWN_PCT = preset["MAX_DRAWDOWN_PCT"]
        CFG.ALLOW_LONG = preset["ALLOW_LONG"]
        CFG.ALLOW_SHORT = preset["ALLOW_SHORT"]
        CFG.TIMEFRAME = preset["TIMEFRAME"]
        CFG.SCAN_INTERVAL_SEC = preset["SCAN_INTERVAL_SEC"]
        CFG.MIN_VOLUME_USDT = preset["MIN_VOLUME_USDT"]
        CFG.EMA_PERIOD = preset["EMA_PERIOD"]
        CFG.BB_PERIOD = preset["BB_PERIOD"]
        CFG.BB_STD = preset["BB_STD"]
        CFG.RSI_PERIOD = preset["RSI_PERIOD"]
        CFG.RSI_OVERSOLD = preset["RSI_OVERSOLD"]
        CFG.RSI_OVERBOUGHT = preset["RSI_OVERBOUGHT"]

        st.session_state.sb_leverage = preset["LEVERAGE"]
        st.session_state.sb_margin = preset["MARGIN_USDT"]
        st.session_state.sb_use_auto_compound = False
        st.session_state.sb_max_pos = preset["MAX_POSITIONS"]
        st.session_state.sb_sl = round(preset["STOP_LOSS_PCT"] * 100, 2)
        st.session_state.sb_tp = round(preset["TAKE_PROFIT_PCT"] * 100, 2)
        st.session_state.sb_timeframe = preset["TIMEFRAME"]
        st.session_state.sb_bb_period = preset["BB_PERIOD"]
        st.session_state.sb_bb_std = preset["BB_STD"]
        st.session_state.sb_rsi_period = preset["RSI_PERIOD"]
        st.session_state.sb_rsi_overbought = float(preset["RSI_OVERBOUGHT"])
        st.session_state.sb_rsi_oversold = float(preset["RSI_OVERSOLD"])
        st.session_state.sb_ssl_period = CFG.SSL_PERIOD
        
        st.session_state.main_leverage = preset["LEVERAGE"]
        st.session_state.main_margin = preset["MARGIN_USDT"]
        st.session_state.main_use_auto_compound = False
        st.session_state.main_max_pos = preset["MAX_POSITIONS"]
        st.session_state.sb_use_dynamic_sltp = getattr(CFG, "USE_DYNAMIC_SLTP", True)
        st.session_state.sb_atr_tp_mult = getattr(CFG, "ATR_TP_MULT", 2.0)
        st.session_state.sb_atr_sl_mult = getattr(CFG, "ATR_SL_MULT", 1.5)
        st.session_state.main_use_dynamic_sltp = getattr(CFG, "USE_DYNAMIC_SLTP", True)
        st.session_state.main_atr_tp_mult = getattr(CFG, "ATR_TP_MULT", 2.0)
        st.session_state.main_atr_sl_mult = getattr(CFG, "ATR_SL_MULT", 1.5)
        st.session_state.main_sl = round(preset["STOP_LOSS_PCT"] * 100, 2)
        st.session_state.main_tp = round(preset["TAKE_PROFIT_PCT"] * 100, 2)
        st.session_state.main_timeframe = preset["TIMEFRAME"]
        st.session_state.main_bb_period = preset["BB_PERIOD"]
        st.session_state.main_bb_std = preset["BB_STD"]
        st.session_state.main_ttm_mom_period = preset["TTM_MOM_PERIOD"]
        
        st.session_state.active_preset = selected

        _engine = st.session_state.get("engine")
        if _engine:
            for attr in ["LEVERAGE", "MARGIN_USDT", "MAX_POSITIONS", "STOP_LOSS_PCT",
                         "TAKE_PROFIT_PCT", "TRAILING_ACTIVATE_PCT", "TRAILING_CALLBACK_PCT",
                         "MAX_DRAWDOWN_PCT", "ALLOW_LONG", "ALLOW_SHORT", "TIMEFRAME",
                         "SCAN_INTERVAL_SEC", "MIN_VOLUME_USDT", "EMA_PERIOD", "BB_PERIOD",
                         "BB_STD", "RSI_PERIOD", "RSI_OVERSOLD", "RSI_OVERBOUGHT"]:
                setattr(_engine.cfg, attr, preset[attr])
            if _engine.trader:
                for attr in ["LEVERAGE", "MARGIN_USDT", "MAX_POSITIONS", "STOP_LOSS_PCT", "TAKE_PROFIT_PCT"]:
                    setattr(_engine.trader.cfg, attr, preset[attr])
            if _engine.scanner:
                for attr in ["TIMEFRAME", "SCAN_INTERVAL_SEC", "MIN_VOLUME_USDT", "EMA_PERIOD", "BB_PERIOD", "BB_STD"]:
                    setattr(_engine.scanner.cfg, attr, preset[attr])
                if _engine.scanner.strategy:
                    for attr in ["EMA_PERIOD", "BB_PERIOD", "BB_STD", "RSI_PERIOD", "RSI_OVERSOLD", "RSI_OVERBOUGHT"]:
                        setattr(_engine.scanner.strategy.cfg, attr, preset[attr])

        CFG.save_settings()
        st.toast(f"⚙️ {selected} 프리셋의 19개 파라미터가 실시간 적용 및 저장되었습니다.")

    st.selectbox(
        "🧠 최적 파라미터 프리셋 적용",
        ["-- 기간을 선택하세요 --"] + list(MULTI_PERIOD_PRESETS.keys()),
        key="multi_period_select",
        on_change=apply_multi_period_preset,
        help="미리 저장해둔 '추천 설정 세트'를 한 번에 불러옵니다. 하나 고르면 값들이 자동으로 바뀌고 바로 저장돼요."
    )

    st.markdown("---")
    st.markdown(
        """
        <style>
        @keyframes cooldownBlink {
            0% { opacity: 1; }
            50% { opacity: 0.35; }
            100% { opacity: 1; }
        }
        .cooldown-ready-blink {
            animation: cooldownBlink 1.1s infinite;
            font-weight: 700;
        }
        .cooldown-hover-wrap {
            position: relative;
            display: inline-block;
            cursor: help;
        }
        .cooldown-hover-tip {
            visibility: hidden;
            opacity: 0;
            width: 270px;
            background: #111827;
            color: #e5e7eb;
            border: 1px solid #374151;
            border-radius: 8px;
            padding: 8px 10px;
            position: absolute;
            z-index: 99999;
            top: 26px;
            left: 0;
            font-size: 11.19px !important;
            line-height: 1.45;
            transition: opacity 0.18s ease;
            box-shadow: 0 8px 20px rgba(0,0,0,0.35);
        }
        .cooldown-hover-wrap:hover .cooldown-hover-tip {
            visibility: visible;
            opacity: 1;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if engine.trader:
        global_cd = engine.trader.get_global_cooldown_left()
        if global_cd > 0:
            st.markdown(f"<span style='color:#ef4444;font-size:0.85rem;'>🔒 글로벌 쿨다운: {global_cd:.1f}초 대기</span>", unsafe_allow_html=True)
        else:
            st.markdown(
                "<span class='cooldown-hover-wrap'>"
                "<span class='cooldown-ready-blink' style='color:#10b981;font-size:1.04rem;font-weight:700;'>🔓 글로벌 쿨다운: 진입 가능</span>"
                "<span class='cooldown-hover-tip'>"
                "이 기능은 '너무 빠른 연속 진입'을 막는 안전장치입니다.<br>"
                "이 쿨다운은 사용자가 직접 켜고 끄는 설정이 아니라, 봇이 자동으로 관리합니다.<br>"
                "지금은 쿨다운이 끝나서 새 진입이 가능한 상태예요.<br><br>"
                "왜 필요하나?<br>"
                "• 과매매(연속 진입) 방지<br>"
                "• 손절 직후 즉시 재진입 방지<br>"
                "• API 지연/체결 꼬임 시 중복 주문 방지"
                "</span></span>",
                unsafe_allow_html=True
            )
            
        cds = engine.trader.cooldowns
        active_cds = {sym: left for sym, left in [(s, engine.trader.get_symbol_cooldown_left(s)) for s in cds] if left > 0}
        if active_cds:
            for s, left in active_cds.items():
                st.markdown(f"<span style='color:#f59e0b;font-size:0.8rem;'>• {s}: {left:.1f}초 대기</span>", unsafe_allow_html=True)

    st.markdown("---")
    st.checkbox("⚡ RSI 필터 강제 스위칭", value=CFG.USE_RSI_FILTER, key="sb_use_rsi_filter", on_change=sync_p, args=("sb_use_rsi_filter", "sb_use_rsi_filter", "USE_RSI_FILTER"),
                help="체크 시 롱/숏 진입 전 RSI 과열 여부를 최종 판별합니다.")
    st.checkbox("⚡ 복리 모드 사용 (총잔고 %)", key="sb_use_auto_compound", on_change=sync_p, args=("sb_use_auto_compound", "main_use_auto_compound", "USE_AUTO_COMPOUND"),
                help="ON: 1회 진입금액 대신 총잔고의 설정 비율(%)을 증거금으로 사용합니다.")
    # [2026-08-29] 같은 위젯에 기본값과 Session State를 동시에 주면 streamlit이
    # 경고를 띄운다. 이 키는 init_session()의 defaults에서 이미 채워지므로
    # 위젯 쪽 기본값을 없애 세션 상태를 단일 출처로 둔다.
    st.number_input("📊 총잔고 사용 비율 (%)", 1.0, 100.0, step=1.0, key="sb_auto_compound_pct",
                    on_change=sync_p, args=("sb_auto_compound_pct", "main_auto_compound_pct", "AUTO_COMPOUND_PCT"),
                    disabled=not bool(st.session_state.get("sb_use_auto_compound", getattr(CFG, "USE_AUTO_COMPOUND", False))))
    
    st.markdown("---")
    st.checkbox(
        "✨ 이중 볼린저 밴드 스윙 청산 로직",
        value=True,
        key="sb_use_dbb_sltp",
        help="8401 봇은 직전 꼬리를 손절로 잡고, 손익비(RR)를 곱해 목표가를 산출하는 스윙 매매 방식을 사용합니다.",
        disabled=True
    )
    st.caption("✅ **현재 로직: 스윙 하이/로우 손절 및 RR 기반 목표가 익절 가동 중**")
    col_dbb1, col_dbb2 = st.columns(2)
    with col_dbb1:
        st.number_input("🎯 목표 손익비 (RR)", 0.5, 10.0, float(getattr(CFG, "DBB_TP_RR", 2.0)), step=0.1, key="sb_dbb_tp_rr", on_change=sync_p, args=("sb_dbb_tp_rr", "main_dbb_tp_rr", "DBB_TP_RR"), disabled=True)
    with col_dbb2:
        st.number_input("🛡️ 최대 손절 (%)", 0.1, 10.0, round(float(getattr(CFG, "MAX_SL_PCT", 0.015)) * 100, 2), step=0.1, format="%.2f", key="sb_max_sl_pct", on_change=sync_p, args=("sb_max_sl_pct", "main_max_sl_pct", "MAX_SL_PCT", True), disabled=True)
    # ── LOSS STREAK COOLDOWN ─────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        '<p style="font-family:\'IBM Plex Mono\',monospace;font-size:0.75rem;color:#ff6600;letter-spacing:0.1em;margin-top:10px;">LOSS STREAK COOLDOWN</p>',
        unsafe_allow_html=True,
    )
    cd1, cd2 = st.columns(2)
    with cd1:
        st.number_input("🔁 연속손실 차단 횟수",
                        0, 10,
                        int(getattr(CFG, "COOLDOWN_LOSS_COUNT", 2)),
                        step=1,
                        key="sb_cooldown_count",
                        on_change=sync_p, args=("sb_cooldown_count", "main_cooldown_count", "COOLDOWN_LOSS_COUNT"))
    with cd2:
        st.number_input("⏱️ 쿨다운 시간 (h)",
                        0.0, 48.0,
                        float(getattr(CFG, "COOLDOWN_HOURS", 8.0)),
                        step=1.0,
                        key="sb_cooldown_hours",
                        on_change=sync_p, args=("sb_cooldown_hours", "main_cooldown_hours", "COOLDOWN_HOURS"))

    # ── 디스코드 ────────────────────────────────────────────
    st.markdown("---")
    st.markdown(
        '<p style="font-family:\'IBM Plex Mono\',monospace;font-size:0.75rem;color:#00e0ff;letter-spacing:0.1em;margin-top:10px;">DISCORD NOTIFICATION</p>',
        unsafe_allow_html=True,
    )
    st.info(
        "📢 **디스코드 Webhook 알림 작동 중**\n\n"
        "현재 봇 알림 채널이 디스코드 채널로 통합되어 있습니다. "
        "모든 포지션 진입/청산 및 시스템 경보가 지정된 채널로 즉시 전송됩니다."
    )

    if st.button("🔔 디스코드 알림 테스트 전송", use_container_width=True):
        from core.alert import send_telegram_alert
        send_telegram_alert("🔔 **[AI QUANTUM]** 디스코드 알림 테스트 메시지 전송 성공!")
        st.success("✅ 테스트 메시지를 전송하였습니다. 디스코드 채널을 확인하세요.")

    # ── 현재 설정 요약 ───────────────────────────────────────
    st.markdown("---")
    st.markdown(
        f"""<div style="font-family:'IBM Plex Mono',monospace;font-size:0.88rem;color:#cccccc;line-height:2.2;">
        <b>[진입]</b> TF: {CFG.TIMEFRAME} | TTM Squeeze 돌파 + 200EMA 필터 + 모멘텀 필터 | 켈트너 배수: {getattr(CFG,'KC_MULT',1.5):.1f} <br>
        <b>[필터]</b> 롱: 캔들상승/모멘텀상승/가격>200EMA | 숏: 캔들하락/모멘텀하락/가격<200EMA | RSI 스위칭: {getattr(CFG,'USE_RSI_FILTER',True)} <br>
        <b>[청산]</b> SL: 스윙 로우/하이 기준 (최대 {getattr(CFG,'MAX_SL_PCT',0.015)*100:.1f}%) | TP: 리스크×{getattr(CFG,'DBB_TP_RR',2.0):.1f} | 트레일링: {getattr(CFG,'USE_TRAILING_STOP',False)} <br>
        <b>[안전장치]</b> 손실후재진입금지: {getattr(CFG,'REENTRY_BLOCK_MIN',15.0):.0f}분 | 시간청산: {getattr(CFG,'MAX_HOLDING_HOURS',6.0):.1f}h (수익유예, 하드캡 {getattr(CFG,'MAX_HOLDING_HARD_HOURS',24.0):.0f}h) | 연패쿨다운: {getattr(CFG,'COOLDOWN_LOSS_COUNT',2)}연→{getattr(CFG,'COOLDOWN_HOURS',8.0):.0f}h <br>
        <b>[매매대상]</b> {"화이트리스트 한정: " + ", ".join(getattr(CFG,'SYMBOL_WHITELIST',[]) or []) if (getattr(CFG,'SYMBOL_WHITELIST',[]) or []) else f"거래대금 상위 {getattr(CFG,'SCAN_TOP_N',10)}종목 자동선정"}
        </div>""",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════
# 메인 헤더 (한 줄 배치)
# ══════════════════════════════════════════════════════
# ── [v4.3.9] 잔상 근본 수정: 전체 리런 → fragment 부분 갱신 ──
# 기존 time.sleep(15)+st.rerun() 전체 리런은 매 갱신마다 페이지 DOM 전체를
# 재구성해, 렌더가 느린 대시보드에서 이전 요소가 stale(흐림) 상태로 겹쳐 보였음.
# fragment(run_every)는 본문 영역만 요소별 in-place 교체하므로 잔상이 원천 차단됨.
_AUTO_REFRESH_SEC = 15

@st.fragment(run_every=_AUTO_REFRESH_SEC if st.session_state.get("auto_trading") else None)
def _main_body():
    st.markdown('<div class="floating-header-wrapper"></div>', unsafe_allow_html=True)
    col_empty, col_time, col_status = st.columns([6.7, 1.8, 1.5])

    with col_empty:
        # ── 초기화(SINCE) 이후 경과 시간 [N일 NN시간 NN분] ──────────────
        _ps = stats_store.load_stats().get("perf_start_time", "2026-07-05 15:54:00")
        try:
            _ps_dt = datetime.strptime(_ps, "%Y-%m-%d %H:%M:%S")
        except Exception:
            _ps_dt = datetime(2026, 5, 27, 22, 6, 0)
        _elapsed = (datetime.utcnow() + timedelta(hours=9)) - _ps_dt
        _el_sec = max(int(_elapsed.total_seconds()), 0)
        _el_days = _el_sec // 86400
        _el_hours = (_el_sec % 86400) // 3600
        _el_mins = (_el_sec % 3600) // 60
        # ── 무진입(A)·무포지션(B) 지속 시간 [N일 NN시간 NN분] ──────────────
        def _fmt_dur(_sec):
            _sec = max(int(_sec), 0)
            return f"[{_sec // 86400:02d}일 {(_sec % 86400) // 3600:02d}시간 {(_sec % 3600) // 60:02d}분]"

        _now_kst2 = datetime.utcnow() + timedelta(hours=9)
        try:
            _pos_cnt = len(dash.get("positions", [])) if dash else 0
        except Exception:
            _pos_cnt = 0
        _last_entry_dt = None
        _last_exit_dt = None
        try:
            import csv as _csv
            _csv_path = os.path.join(os.path.dirname(__file__), "data", "trade_history.csv")
            with open(_csv_path, encoding="utf-8-sig") as _f:
                for _row in _csv.DictReader(_f):
                    _t = (_row.get("시간") or "").strip()
                    if not _t:
                        continue
                    try:
                        _dt = datetime.strptime(_t, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        continue
                    _typ = (_row.get("유형") or "").strip()
                    if _typ == "진입":
                        _last_entry_dt = _dt
                    elif _typ == "청산":
                        _last_exit_dt = _dt
        except Exception:
            pass

        # [8405 이식] 포지션 보유 중이면 0, 기록 없으면 앱 시작 시각 기준으로 표시
        _app_start = st.session_state.get("_app_start_time", _now_kst2)
        if _pos_cnt > 0:
            _idle_a = 0
            _idle_b = 0
        else:
            _idle_a_base = _last_entry_dt if _last_entry_dt else _app_start
            _idle_a = (_now_kst2 - _idle_a_base).total_seconds()
            _idle_b_base = _last_exit_dt if _last_exit_dt else _app_start
            _idle_b = (_now_kst2 - _idle_b_base).total_seconds()
        _a_base = _last_entry_dt.strftime("%Y-%m-%d %H:%M") if _last_entry_dt else _app_start.strftime("%Y-%m-%d %H:%M (앱시작)")
        _b_base = _last_exit_dt.strftime("%Y-%m-%d %H:%M") if _last_exit_dt else _app_start.strftime("%Y-%m-%d %H:%M (앱시작)")
        _tf_str = getattr(CFG, "TIMEFRAME", "15m")
        _is_bf = getattr(CFG, "USE_BLUEFROG", False)
        _mode_tag = '<span style="color:#ff5a5a;font-weight:bold;margin-right:4px;">[역]</span>' if _is_bf else '<span style="color:#4d9fff;font-weight:bold;margin-right:4px;">[순]</span>'

        st.markdown(
            f'<div class="header-elapsed-row">'
            f'  <span class="elapsed-since" '
            f'title="수익률·승률 초기화(SINCE {_ps_dt.strftime("%Y-%m-%d %H:%M")}) 이후 경과한 시간입니다.">'
            f'{_mode_tag}&lt;{_tf_str}&gt; [{_el_days:02d}일 {_el_hours:02d}시간 {_el_mins:02d}분]</span>'
            f'  <span class="idle-since" '
            f'title="A) 마지막 진입({_a_base}) 이후 신규 진입이 없는 기간입니다.">'
            f'⏸무진입 {_fmt_dur(_idle_a)}</span>'
            f'  <span class="idle-since" '
            f'title="B) 마지막 청산({_b_base})으로 무포지션이 된 이후 경과 기간입니다.">'
            f'⏸무포지션 {_fmt_dur(_idle_b)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with col_time:
        now_kst = datetime.utcnow() + timedelta(hours=9)
        st.markdown(
            f'<div class="header-btn-like">'
            f'{now_kst.strftime("%Y-%m-%d %H:%M:%S")} KST</div>',
            unsafe_allow_html=True,
        )

    with col_status:
        _engine = st.session_state.get("engine")
        is_live = False
        if _engine and _engine.is_ready:
            if st.session_state.get("auto_trading", False):
                is_live = True

        if is_live:
            # ── 시장 국면 집계 (스캐너 결과 다수결) ─────────────────────
            _scan_results = []
            try:
                if _engine and _engine.scanner:
                    _scan_results = _engine.get_scan_results() or []
            except Exception:
                _scan_results = []

            _adx_thresh  = float(getattr(CFG, 'REGIME_ADX_THRESHOLD', 25.0))
            _adx_period  = int(getattr(CFG, 'ADX_PERIOD', 14))
            _ema_period  = int(getattr(CFG, 'EMA_PERIOD', 139))

            _regime_counts = {"상승 추세장": 0, "하락 추세장": 0, "횡보/조정장": 0}
            for _r in _scan_results:
                _rv = _r.get("regime", "")
                if _rv in _regime_counts:
                    _regime_counts[_rv] += 1

            _total_signals = sum(_regime_counts.values())
            if _total_signals > 0:
                _dominant = max(_regime_counts, key=_regime_counts.get)
            else:
                _dominant = "횡보/조정장"

            _bull_cnt  = _regime_counts["상승 추세장"]
            _bear_cnt  = _regime_counts["하락 추세장"]
            _side_cnt  = _regime_counts["횡보/조정장"]

            if _dominant == "상승 추세장":
                _badge_cls  = "header-btn-like header-badge-live-bull"
                _regime_label = "🔴 상승장 LIVE"
                _tooltip_text = (
                    f"📈 상승장입니다\n"
                    f"(ADX ≥ {_adx_thresh:.0f} + 가격 > EMA{_ema_period})\n"
                    f"─────────────────────\n"
                    f"기준: BTC 1개 기준이 아니라\n"
                    f"스캔 대상 전체 심볼(보통 25개) 다수결 기준\n"
                    f"─────────────────────\n"
                    f"📊 스캔 결과 {_total_signals}개 심볼 기준\n"
                    f"  • 상승 추세장: {_bull_cnt}개\n"
                    f"  • 하락 추세장: {_bear_cnt}개\n"
                    f"  • 횡보/조정장: {_side_cnt}개"
                )
            elif _dominant == "하락 추세장":
                _badge_cls  = "header-btn-like header-badge-live-bear"
                _regime_label = "🔵 하락장 LIVE"
                _tooltip_text = (
                    f"📉 하락장입니다\n"
                    f"(ADX ≥ {_adx_thresh:.0f} + 가격 < EMA{_ema_period})\n"
                    f"─────────────────────\n"
                    f"기준: BTC 1개 기준이 아니라\n"
                    f"스캔 대상 전체 심볼(보통 25개) 다수결 기준\n"
                    f"─────────────────────\n"
                    f"📊 스캔 결과 {_total_signals}개 심볼 기준\n"
                    f"  • 상승 추세장: {_bull_cnt}개\n"
                    f"  • 하락 추세장: {_bear_cnt}개\n"
                    f"  • 횡보/조정장: {_side_cnt}개"
                )
            else:
                _badge_cls  = "header-btn-like header-badge-live"
                _regime_label = "🟢 횡보장 LIVE"
                _tooltip_text = (
                    f"➡ 횡보장입니다\n"
                    f"(ADX < {_adx_thresh:.0f} · 방향성 약함)\n"
                    f"─────────────────────\n"
                    f"기준: BTC 1개 기준이 아니라\n"
                    f"스캔 대상 전체 심볼(보통 25개) 다수결 기준\n"
                    f"─────────────────────\n"
                    f"📊 스캔 결과 {_total_signals}개 심볼 기준\n"
                    f"  • 상승 추세장: {_bull_cnt}개\n"
                    f"  • 하락 추세장: {_bear_cnt}개\n"
                    f"  • 횡보/조정장: {_side_cnt}개"
                )

            st.markdown(
                f'<div class="live-badge-wrap">'
                f'  <div class="{_badge_cls}">'
                f'    <span class="dot"></span>{_regime_label}'
                f'  </div>'
                f'  <div class="live-tooltip">{_tooltip_text}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="header-btn-like header-badge-stopped">'
                '<span class="dot"></span>STOPPED</div>',
                unsafe_allow_html=True,
            )

    # ══════════════════════════════════════════════════════
    # 탭 구성
    # ══════════════════════════════════════════════════════
    # [v3.1.81] st.tabs는 리런 시 항상 첫 탭으로 되돌아가는 한계가 있어
    # (자동 15초 리런·버튼 클릭 시 대시보드로 튕김) → session_state 라디오로 교체.
    # key="active_tab"이 선택을 기억하므로 리런 후에도 현재 탭이 유지된다.
    st.markdown(
        """
        <style>
        div[role="radiogroup"][aria-label="main-nav"] { gap: 4px; }
        div[role="radiogroup"][aria-label="main-nav"] > label {
            background: rgba(13,17,33,0.55);
            border: 1px solid var(--terminal-border);
            border-radius: 10px 10px 0 0;
            padding: 8px 16px; margin: 0;
            font-weight: 700;
        }
        div[role="radiogroup"][aria-label="main-nav"] > label:hover {
            border-color: var(--terminal-accent);
        }
        div[role="radiogroup"][aria-label="main-nav"] input { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── [실매매 엔진 상태] bot.py 하트비트로 '실제 매매 가능여부'를 명확히 표시 ──
    #    (LIVE/횡보장 배지는 app.py 자체 엔진 상태일 뿐 → bot.py가 죽어도 착시 발생하던 문제 해소)
    try:
        _eng = read_engine_liveness(threshold_sec=30.0)
        _hb = _eng.get("last_heartbeat") or "기록 없음"
        _pid = _eng.get("pid") or "?"
        if not _eng["alive"]:
            st.error(
                f"🔴 **실매매 불가 — 매매엔진(bot.py) 미실행**  ·  대시보드만 표시 중이며 "
                f"**실제 진입·자동청산(트레일링/시간청산)이 작동하지 않습니다.**  ·  "
                f"마지막 하트비트: {_hb}  →  bot.py를 재가동하세요."
            )
        elif _eng["trading_enabled"]:
            st.success(
                f"🟢 **실매매 가능 — ENGINE LIVE** (자동매매 ON)  ·  "
                f"스캐너 {'ON' if _eng['scanner_on'] else 'OFF'} · 포지션 {_eng['n_pos']}개 · "
                f"PID {_pid} · 하트비트 {_hb}"
            )
        else:
            st.warning(
                f"🟡 **엔진 실행중 · 자동매매 OFF**  ·  신규 진입은 차단되고 **보유 포지션 관리만** 수행됩니다.  ·  "
                f"포지션 {_eng['n_pos']}개 · PID {_pid} · 하트비트 {_hb}"
            )
    except Exception:
        pass

    _TAB_LABELS = [
        "📊  대시보드",
        "🔍  스캐너",
        "📋  매매 이력",
        "⚙️  설정",
    ]
    active_tab = st.radio(
        "main-nav",
        _TAB_LABELS,
        key="active_tab",
        horizontal=True,
        label_visibility="collapsed",
    )

    if active_tab == _TAB_LABELS[0]:
        render_dashboard(engine)
    elif active_tab == _TAB_LABELS[1]:
        render_scanner(engine)
    elif active_tab == _TAB_LABELS[2]:
        render_history(engine)
    elif active_tab == _TAB_LABELS[3]:
        render_settings(engine)

    # 렌더 도중 요청된 리런은 본문 렌더 완료 후 전체 앱 기준으로 1회 수행
    if st.session_state.pop("_pending_rerun", False):
        st.rerun(scope="app")

_main_body()
