"""
AI QUANTUM — Scanner Tab View Component
8401 스캐너 탭: 개별 진입조건 만족 여부를 ✅/❌로 직관 표기
"""
import streamlit as st
import pandas as pd
from core.engine import QuantumEngine
from core.config import CFG

def render_scanner(engine: QuantumEngine):
    if not st.session_state.api_connected or not engine.is_ready:
        st.info("사이드바에서 OKX API를 연결하세요.")
        return

    # 상태 배지 및 마지막 스캔 시각 표시 영역
    # UI는 자체 engine.scanner 대신 파일 기반 시간을 씁니다.
    last = engine.get_last_scan_time()
    last_scan_str = f"마지막 스캔: {last.strftime('%H:%M:%S')}" if last else "마지막 스캔: 대기 중"
    
    c_status, c_time = st.columns([2, 1])
    with c_status:
        # 항상 매매 봇이 백그라운드에서 스캔하고 있다고 가정 (is_running 제거)
        preset = st.session_state.active_preset
        badge_class = "badge-green-blink"
        if "1차" in preset:
            badge_class = "badge-pink-blink"
        elif "2차" in preset:
            badge_class = "badge-red-blink"
            
        st.markdown(
            f'<div class="{badge_class}">📡 {preset} 스캐너 백그라운드 실시간 동기화 중</div>',
            unsafe_allow_html=True
        )
    with c_time:
        st.markdown(
            f'<p style="font-family:\'IBM Plex Mono\',monospace;font-size:0.85rem;color:#888;text-align:right;margin-top:5px;">{last_scan_str}</p>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-bottom:15px;'></div>", unsafe_allow_html=True)
    
    results = engine.get_scan_results()

    if results:
        df_scan = pd.DataFrame(results)

        # 신호 필터
        def notify_signal_filter():
            st.toast(f"🔍 신호 필터가 변경되었습니다: {st.session_state.scanner_signal_filter}")
        signal_filter = st.selectbox(
            "🔍 신호 필터 선택",
            ["전체", "LONG 신호", "SHORT 신호", "신호 없음"],
            key="scanner_signal_filter",
            on_change=notify_signal_filter
        )
        if signal_filter == "LONG 신호":
            df_scan = df_scan[df_scan["signal"] == "long"]
        elif signal_filter == "SHORT 신호":
            df_scan = df_scan[df_scan["signal"] == "short"]
        elif signal_filter == "신호 없음":
            df_scan = df_scan[df_scan["signal"] == "none"]

        # ── 조건별 만족 개수 열 추가 ──
        a_cols = ["trend_ok", "ema_align_ok", "pullback_ok", "rsi_range_ok"]
        b_cols = ["bb_break_ok", "bb_rsi_ok"]
        
        def format_attainment(row):
            a_count = sum(bool(row.get(c, False)) for c in a_cols)
            b_count = sum(bool(row.get(c, False)) for c in b_cols)
            # 조건이 충족되어 매매신호가 발생한 경우 하이라이트
            res = f"[A] {a_count}/4"
            if a_count == 4:
                res = f"🔥 [A] 4/4 (진입)"
            res += f"  |  [B] {b_count}/2"
            if b_count == 2:
                res += f" 🔥 (진입)"
            return res

        if not df_scan.empty:
            df_scan["cond_count"] = df_scan.apply(format_attainment, axis=1)
        else:
            df_scan["cond_count"] = ""

        # ── 표시 컬럼 구성 ──
        cols = ["symbol", "price", "change_pct", "signal", "strength", "cond_count"]
        col_names = ["종목", "현재가", "등락(%)", "신호", "강도(%)", "셋업 진행도"]

        # 개별 진입조건 6개 컬럼
        cond_map = [
            ("trend_ok", "A:추세"),
            ("ema_align_ok", "A:EMA정렬"),
            ("pullback_ok", "A:눌림목"),
            ("rsi_range_ok", "A:RSI"),
            ("bb_break_ok", "B:BB반등"),
            ("bb_rsi_ok", "B:침체RSI"),
        ]
        for col, label in cond_map:
            if col in df_scan.columns:
                cols.append(col)
                col_names.append(label)

        # RSI 수치 및 사유
        cols.extend(["rsi", "reason"])
        col_names.extend(["RSI", "진입 사유"])

        display = df_scan[cols].copy()
        display.columns = col_names

        # ── 신호 아이콘 매핑 ──
        display["신호"] = display["신호"].map({"long": "🟢 LONG", "short": "🔴 SHORT", "none": "— "})

        # ── 개별 조건 ✅/❌ 매핑 ──
        for _, label in cond_map:
            if label in display.columns:
                display[label] = display[label].map({True: "✅", False: "❌"})

        # ── 스타일링 ──
        def style_pnl(val):
            color = '#ef4444' if val >= 0 else '#3b82f6'
            return f'color: {color}; font-weight: bold;'

        styler = display.style
        if "등락(%)" in display.columns:
            styler = styler.map(style_pnl, subset=["등락(%)"])

        st.dataframe(
            styler,
            use_container_width=True,
            height=600,
            hide_index=True,
        )

        # ── 범례 ──
        # ── 범례 ──
        st.markdown("""
<div style="font-size:0.78rem;color:#888;font-family:'IBM Plex Mono',monospace;margin-top:8px;line-height:1.7;">
    <b>📖 진입조건 범례 (둘 중 하나만 100% 달성 시 즉시 진입)</b><br>
    <b>[A전략: 눌림목 셋업] (4개 동시 만족 시 진입)</b><br>
    - <b>A:추세</b>: 가격 vs EMA200 (롱: 가격≥EMA200 / 숏: 가격<EMA200)<br>
    - <b>A:EMA정렬</b>: 단기 EMA9 vs EMA21 (롱: 9>21 / 숏: 9<21)<br>
    - <b>A:눌림목</b>: 가격이 EMA9에 0.2% 이내로 근접<br>
    - <b>A:RSI</b>: 적정 구간 (롱: 40~65 / 숏: 35~60)<br>
    <b>[B전략: 밴드 반등 셋업] (2개 동시 만족 시 진입)</b><br>
    - <b>B:BB반등</b>: 전봉 BB이탈 → 현봉 BB안쪽 복귀<br>
    - <b>B:침체RSI</b>: BB 복귀 시 RSI 보조확인 (롱: RSI<45 / 숏: RSI>55)<br>
    <span style="color:#4ade80;">✅ = 조건 충족</span> &nbsp;|&nbsp; <span style="color:#ef4444;">❌ = 미충족</span>
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown(
            '<p style="color:#555;font-family:\'IBM Plex Mono\',monospace;">스캔 결과 없음 — 자동매매가 시작되면 결과가 이곳에 표시됩니다.</p>',
            unsafe_allow_html=True,
        )
