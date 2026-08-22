#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8402 봇 롱/숏 진입 기준 PDF 생성 스크립트
"""
import os
import shutil
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm, inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 폰트 등록
FONT_PATH = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"
if not os.path.exists(FONT_PATH):
    FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
pdfmetrics.registerFont(TTFont("AppleGothic", FONT_PATH))

# 색상 정의
PRIMARY = colors.HexColor("#1A365D")    # 네이비
SECONDARY = colors.HexColor("#2B6CB0")  # 블루
LONG_COLOR = colors.HexColor("#22543D") # 롱 그린
LONG_BG = colors.HexColor("#F0FFF4")
SHORT_COLOR = colors.HexColor("#742A2A")# 숏 레드
SHORT_BG = colors.HexColor("#FFF5F5")
DARK_TEXT = colors.HexColor("#2D3748")
LIGHT_BG = colors.HexColor("#F7FAFC")
BORDER_COLOR = colors.HexColor("#E2E8F0")
ACCENT = colors.HexColor("#D69E2E")

def create_pdf(filename="진입.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    
    # 커스텀 스타일
    title_style = ParagraphStyle(
        "DocTitle",
        fontName="AppleGothic",
        fontSize=20,
        leading=26,
        textColor=PRIMARY,
        alignment=1, # Center
        spaceAfter=6,
    )
    
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        fontName="AppleGothic",
        fontSize=11,
        leading=16,
        textColor=SECONDARY,
        alignment=1,
        spaceAfter=15,
    )

    h1_style = ParagraphStyle(
        "Heading1_Custom",
        fontName="AppleGothic",
        fontSize=13,
        leading=18,
        textColor=PRIMARY,
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True,
    )

    h2_style = ParagraphStyle(
        "Heading2_Custom",
        fontName="AppleGothic",
        fontSize=11,
        leading=15,
        textColor=SECONDARY,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True,
    )

    body_style = ParagraphStyle(
        "Body_Custom",
        fontName="AppleGothic",
        fontSize=9,
        leading=13.5,
        textColor=DARK_TEXT,
        spaceAfter=4,
    )

    body_bold = ParagraphStyle(
        "Body_Bold",
        fontName="AppleGothic",
        fontSize=9,
        leading=13.5,
        textColor=DARK_TEXT,
    )

    table_header_style = ParagraphStyle(
        "TableHeader",
        fontName="AppleGothic",
        fontSize=9,
        leading=12,
        textColor=colors.white,
        alignment=1,
    )

    table_cell_style = ParagraphStyle(
        "TableCell",
        fontName="AppleGothic",
        fontSize=8.5,
        leading=12,
        textColor=DARK_TEXT,
    )
    
    table_cell_center = ParagraphStyle(
        "TableCellCenter",
        fontName="AppleGothic",
        fontSize=8.5,
        leading=12,
        textColor=DARK_TEXT,
        alignment=1,
    )

    elements = []

    # ── 제목 영역 ──
    elements.append(Paragraph("8402 봇 세력흔적 전략 롱·숏(Long/Short) 진입 기준 가이드", title_style))
    elements.append(Paragraph("15분봉 완성 캔들 기반 세력라인 & 마지노선 양방향 매매 기법 명세서 (v9.10.0)", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceAfter=10))

    # ── 1. 전략 개요 ──
    elements.append(Paragraph("1. 전략 개요 및 핵심 지표 정의", h1_style))
    
    overview_text = (
        "<b>전략명</b>: 15분봉 세력 흔적 찾기 단타 전략 (Sniper15)<br/>"
        "<b>운용 방식</b>: 15분봉 <b>완성 캔들(종가 확정)</b>만을 분석하여, 거래량 폭증과 신고가/신저가 돌파, "
        "세력라인 및 마지노선 동시 돌파 시 <b>롱(Long) 및 숏(Short) 포지션</b>에 진입하는 양방향 추세 추종 단타 기법입니다."
    )
    elements.append(Paragraph(overview_text, body_style))
    elements.append(Spacer(1, 4))

    # 핵심 지표 표
    ind_data = [
        [Paragraph("지표 / 라인명", table_header_style), Paragraph("수식 및 파라미터", table_header_style), Paragraph("기능 및 역할", table_header_style)],
        [
            Paragraph("<b>세력라인 (Fast)</b>", table_cell_style),
            Paragraph("ATR(10) 승수 1.9 기반 상·하한 추종선", table_cell_style),
            Paragraph("단기 세력 유입 및 급격한 가격 변동 감지선", table_cell_style)
        ],
        [
            Paragraph("<b>마지노선 (Slow)</b>", table_cell_style),
            Paragraph("ATR(10) 승수 1.96 기반 상·하한 추종선", table_cell_style),
            Paragraph("추세 이탈 기준선이자 <b>손절(SL) 기준 가격</b>", table_cell_style)
        ],
        [
            Paragraph("<b>거래량 이평 (VEMA)</b>", table_cell_style),
            Paragraph("20봉 지수이동평균 (EMA 20)", table_cell_style),
            Paragraph("평균 거래량 대비 수급 폭증(V > VEMA) 필터", table_cell_style)
        ],
        [
            Paragraph("<b>15봉 중심값</b>", table_cell_style),
            Paragraph("(Highest(H, 15) + Lowest(L, 15)) / 2", table_cell_style),
            Paragraph("최근 15봉 가격 박스권의 중간 중심선", table_cell_style)
        ],
    ]
    
    ind_table = Table(ind_data, colWidths=[38 * mm, 62 * mm, 80 * mm])
    ind_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(ind_table)
    elements.append(Spacer(1, 10))

    # ── 2. 롱(Long) 진입 기준 ──
    elements.append(Paragraph("2. 롱(Long / 매수) 포지션 진입 기준", h1_style))
    
    long_desc = "롱 포지션은 <b>아래 5대 신호 수식 조건과 세력라인/마지노선 상향 돌파</b>가 동일 캔들에서 100% 동시 충족될 때 진입합니다."
    elements.append(Paragraph(long_desc, body_style))
    elements.append(Spacer(1, 3))

    long_data = [
        [Paragraph("구분", table_header_style), Paragraph("수식 조건 (원문)", table_header_style), Paragraph("상세 판정 기준", table_header_style)],
        [Paragraph("<b>X1</b>", table_cell_center), Paragraph("C > Highest(C, 15)", table_cell_style), Paragraph("15분봉 종가가 최근 15개봉의 최고 종가를 상향 돌파 (신고가 갱신)", table_cell_style)],
        [Paragraph("<b>X2</b>", table_cell_center), Paragraph("C(1) < Highest(C, 15, 1)", table_cell_style), Paragraph("직전 봉은 미돌파 상태 (당봉에서 최초로 돌파 발생)", table_cell_style)],
        [Paragraph("<b>X3</b>", table_cell_center), Paragraph("C > O", table_cell_style), Paragraph("당봉이 상승 <b>양봉</b>으로 마감", table_cell_style)],
        [Paragraph("<b>X4</b>", table_cell_center), Paragraph("V > eavg(V, 20)", table_cell_style), Paragraph("당봉 거래량이 최근 20봉 거래량 지수이평을 상회 (수급 폭증)", table_cell_style)],
        [Paragraph("<b>X5</b>", table_cell_center), Paragraph("C > (Highest(H,15) + Lowest(L,15))/2", table_cell_style), Paragraph("종가가 최근 15봉 고저 중간값보다 위에서 마감", table_cell_style)],
        [Paragraph("<b>라인돌파</b>", table_cell_center), Paragraph("C > Fast AND C > Slow", table_cell_style), Paragraph("종가가 <b>세력라인과 마지노선을 둘 다 상향 돌파</b>", table_cell_style)],
    ]
    long_table = Table(long_data, colWidths=[20 * mm, 65 * mm, 95 * mm])
    long_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LONG_COLOR),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LONG_BG, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    elements.append(long_table)
    elements.append(Spacer(1, 4))

    long_mgmt = (
        "<b>[롱 청산 및 손익 관리 규칙]</b><br/>"
        "• <b>손절가 (SL)</b>: 진입 시점의 마지노선(Slow) 가격 (최소 손절폭: 0.5%, 최대 손절 상한 캡: 15.0%)<br/>"
        "• <b>1차 익절가 (TP)</b>: 진입가 대비 <b>+5.0%</b> 도달 시 보유 수량의 50% 분할 익절<br/>"
        "• <b>잔량 추종 (Trailing)</b>: 1차 익절 완료 후 잔여 물량은 마지노선(Slow)을 종가로 하향 이탈할 때까지 추종"
    )
    elements.append(Paragraph(long_mgmt, body_style))
    elements.append(Spacer(1, 10))

    # ── 3. 숏(Short) 진입 기준 ──
    elements.append(Paragraph("3. 숏(Short / 매도) 포지션 진입 기준", h1_style))
    
    short_desc = "숏 포지션은 <b>아래 5대 신호 수식 조건과 세력라인/마지노선 하향 이탈</b>이 동일 캔들에서 100% 동시 충족될 때 진입합니다."
    elements.append(Paragraph(short_desc, body_style))
    elements.append(Spacer(1, 3))

    short_data = [
        [Paragraph("구분", table_header_style), Paragraph("수식 조건 (대칭 수식)", table_header_style), Paragraph("상세 판정 기준", table_header_style)],
        [Paragraph("<b>S1</b>", table_cell_center), Paragraph("C < Lowest(C, 15)", table_cell_style), Paragraph("15분봉 종가가 최근 15개봉의 최저 종가를 하향 이탈 (신저가 갱신)", table_cell_style)],
        [Paragraph("<b>S2</b>", table_cell_center), Paragraph("C(1) > Lowest(C, 15, 1)", table_cell_style), Paragraph("직전 봉은 미이탈 상태 (당봉에서 최초로 이탈 발생)", table_cell_style)],
        [Paragraph("<b>S3</b>", table_cell_center), Paragraph("C < O", table_cell_style), Paragraph("당봉이 하락 <b>음봉</b>으로 마감", table_cell_style)],
        [Paragraph("<b>S4</b>", table_cell_center), Paragraph("V > eavg(V, 20)", table_cell_style), Paragraph("당봉 거래량이 최근 20봉 거래량 지수이평을 상회 (매도세 폭증)", table_cell_style)],
        [Paragraph("<b>S5</b>", table_cell_center), Paragraph("C < (Highest(H,15) + Lowest(L,15))/2", table_cell_style), Paragraph("종가가 최근 15봉 고저 중간값보다 아래에서 마감", table_cell_style)],
        [Paragraph("<b>라인이탈</b>", table_cell_center), Paragraph("C < Fast AND C < Slow", table_cell_style), Paragraph("종가가 <b>세력라인과 마지노선을 둘 다 하향 이탈</b>", table_cell_style)],
    ]
    short_table = Table(short_data, colWidths=[20 * mm, 65 * mm, 95 * mm])
    short_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SHORT_COLOR),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [SHORT_BG, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    elements.append(short_table)
    elements.append(Spacer(1, 4))

    short_mgmt = (
        "<b>[숏 청산 및 손익 관리 규칙]</b><br/>"
        "• <b>손절가 (SL)</b>: 진입 시점의 마지노선(Slow) 가격 (현재가 상단 위치, 최소 손절폭: 0.5%, 최대 손절 상한 캡: 15.0%)<br/>"
        "• <b>1차 익절가 (TP)</b>: 진입가 대비 <b>-5.0%</b> 도달 시 보유 수량의 50% 분할 익절<br/>"
        "• <b>잔량 추종 (Trailing)</b>: 1차 익절 완료 후 잔여 물량은 마지노선(Slow)을 종가로 상향 돌파할 때까지 추종"
    )
    elements.append(Paragraph(short_mgmt, body_style))
    elements.append(Spacer(1, 10))

    # ── 4. 주요 안전장치 및 운용 파라미터 ──
    elements.append(Paragraph("4. 안전장치 및 리스크 관리 가드", h1_style))
    
    safeguards = (
        "1. <b>완성 캔들 종가 원칙</b>: 실시간 틱 흔들림에 의한 휩쏘(Whipsaw)를 방지하기 위해 반드시 완성된 15분봉 종가만 판정.<br/>"
        "2. <b>과대 손절폭 차단</b>: 마지노선까지의 거리가 15.0%를 초과하는 변동성 이상 종목은 진입을 원천 차단(관망).<br/>"
        "3. <b>포지션 분산 & 마진 관리</b>: 최대 동시 보유 포지션 3개(MAX_POSITIONS=3), 격리 5배 레버리지, 계좌 잔고 기반 자동 복리(15%) 적용.<br/>"
        "4. <b>연패 쿨다운 가드</b>: 2회 연속 손실 발생 시 해당 종목은 8시간 동안 재진입 차단."
    )
    elements.append(Paragraph(safeguards, body_style))
    elements.append(Spacer(1, 12))
    elements.append(HRFlowable(width="100%", thickness=0.8, color=BORDER_COLOR, spaceAfter=8))
    
    footer_text = Paragraph("<font color='#718096'>작성일: 2026-08-23 | 대상 봇: 8402_OKX | 엔진 버전: v9.10.0 | 전략: Sniper15</font>", body_style)
    elements.append(footer_text)

    doc.build(elements)
    print(f"✅ PDF 생성 완료: {filename}")

if __name__ == "__main__":
    create_pdf("/Users/l/project/8888/진입.pdf")
    shutil.copy2("/Users/l/project/8888/진입.pdf", "/Users/l/project/8402/진입.pdf")
    print("✅ 8888 및 8402 폴더에 진입.pdf 복사 완료")
