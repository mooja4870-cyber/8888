import os

path = "/Users/l/project/8410/app.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

target1 = """    st.markdown(
        '<div class="quantum-logo" style="letter-spacing:-0.5px;" '
        f'title="[볼린저 밴드 돌파 · {_tf}]&#10;'
        f'1. 밴드 산출: {_bp}봉 이동평균 ± 표준편차 × {_bs}&#10;'
        '2. 진입: 종가가 상단 돌파 시 롱, 하단 돌파 시 숏&#10;'
        '3. 밴드 안에서는 진입하지 않음 (횡보 구간 회피)&#10;'
        f'4. 청산: 손절 ATR×{_slm}, 익절 ATR×{_tpm} (손익비 1:2)">'
        f'<span style="color:#ffffff; font-size: 100%;">8410 [BBTS 변동성 돌파]</span><br>\\n<span style="font-size:15px; color:#888; font-family:\\'JetBrains Mono\\', monospace;">SINCE {_since_disp}</span></div>',
        unsafe_allow_html=True,
    )"""

replace1 = """    st.markdown(
        '<div class="quantum-logo" style="letter-spacing:-0.5px;" '
        f'title="[퓨전 탄력매매 (MR+BBTS) · {_tf}]&#10;'
        '1. 횡보 국면 (ADX<25): 유형2 BB MR 평균회귀 (밴드 이탈 & RSI 극단 시 중심선 회귀)&#10;'
        '2. 추세 국면 (ADX≥25): 유형3 BBTS 추세돌파 (밴드 상/하단 돌파 시 추세 추종)&#10;'
        f'3. 손절: ATR×{_slm}, 익절: MR=중심선 / BBTS=ATR×{_tpm}">'
        f'<span style="color:#ffffff; font-size: 100%;">8410 [FUSION 퓨전 탄력매매]</span><br>\\n<span style="font-size:15px; color:#888; font-family:\\'JetBrains Mono\\', monospace;">SINCE {_since_disp}</span></div>',
        unsafe_allow_html=True,
    )"""

target2 = """        <b style="color:#e5e7eb;">📐 매매 설정 (실제 적용값)</b><br>
        · 전략 &nbsp;<span style="color:#e5e7eb;">볼린저 밴드 돌파</span><br>"""

replace2 = """        <b style="color:#e5e7eb;">📐 매매 설정 (실제 적용값)</b><br>
        · 전략 &nbsp;<span style="color:#e5e7eb;">유형2+유형3 퓨전 (MR+BBTS)</span><br>"""

if target1 not in text:
    print("ERROR: target1 not found")
elif target2 not in text:
    print("ERROR: target2 not found")
else:
    text = text.replace(target1, replace1).replace(target2, replace2)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("SUCCESS: 8410 app.py sidebar updated")
