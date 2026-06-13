"""
8888 봇 통합 관제 — Streamlit Cloud 배포용 래퍼.
로컬 PC가 Gist로 올린 스냅샷 JSON을 읽어 기존 대시보드 UI(dashboard_cloud.html)로 표시.
※ 실거래 API 키는 클라우드에 올리지 않음 — 잔고·포지션 '요약 JSON'만 읽음.

배포(Streamlit Cloud):
  1) 이 repo를 Streamlit Cloud에 연결, main 파일 = streamlit_app.py
  2) App settings → Secrets 에 아래 1줄 추가:
       SNAPSHOT_URL = "https://gist.githubusercontent.com/<user>/<gistid>/raw/snapshot.json"
"""
import pathlib
import streamlit as st

st.set_page_config(page_title="봇 통합 관제", layout="wide", initial_sidebar_state="collapsed")

# 스냅샷 URL: Streamlit secrets 우선, 없으면 안내
snapshot_url = st.secrets.get("SNAPSHOT_URL", "") if hasattr(st, "secrets") else ""
if not snapshot_url:
    st.error("SNAPSHOT_URL 미설정 — App settings → Secrets 에 `SNAPSHOT_URL`(로컬이 올린 Gist raw URL)을 넣어주세요.")
    st.stop()

html = pathlib.Path(__file__).with_name("dashboard_cloud.html").read_text(encoding="utf-8")
html = html.replace("__SNAPSHOT_URL__", snapshot_url)

# 기존 대시보드 HTML 그대로 렌더(카드·순위 메달·정렬·깜빡임 모두 재사용)
st.components.v1.html(html, height=1600, scrolling=True)
