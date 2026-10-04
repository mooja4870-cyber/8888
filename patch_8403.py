import re

filepath = "/Users/l/project/8403/core/strategy.py"
with open(filepath, "r") as f:
    content = f.read()

# Chunk 1: Import Wilder's RSI calculation inside generate_signal or add it
old_calc = """            # ATR 계산
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(window=14).mean()"""

new_calc = """            # ATR 계산
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs()
            ], axis=1).max(axis=1)
            atr = tr.rolling(window=14).mean()
            
            # RSI 계산 (Wilder)
            delta = close.diff()
            gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
            loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
            rs = gain / loss
            rsi_series = 100 - (100 / (1 + rs))"""

content = content.replace(old_calc, new_calc)

# Chunk 2: Fetch RSI latest value
old_vars = """            # 최신 값
            c = close.iloc[-1]
            up = upper.iloc[-1]
            dn = lower.iloc[-1]
            a = atr.iloc[-1]

            if pd.isna(c) or pd.isna(up) or pd.isna(dn) or pd.isna(a):"""

new_vars = """            # 최신 값 (완성봉 기준)
            c = close.iloc[-2]
            up = upper.iloc[-2]
            dn = lower.iloc[-2]
            sma_val = sma.iloc[-2]
            a = atr.iloc[-2]
            rsi = rsi_series.iloc[-2]

            if pd.isna(c) or pd.isna(up) or pd.isna(dn) or pd.isna(a) or pd.isna(rsi):"""

content = content.replace(old_vars, new_vars)

# Chunk 3: The Logic
old_logic = """            # 돌파 로직
            direction = "none"
            sl_price = 0.0
            tp_price = 0.0

            if c > up:
                direction = "long"
                sl_price = c - (a * self.sl_atr_mult)
                tp_price = c + (a * self.tp_atr_mult)
            elif c < dn:
                direction = "short"
                sl_price = c + (a * self.sl_atr_mult)
                tp_price = c - (a * self.tp_atr_mult)"""

new_logic = """            # BB 평균회귀 + RSI 극단 (백테스트 최적화 타점)
            direction = "none"
            sl_price = 0.0
            tp_price = 0.0
            
            # 파라미터 강제 주입
            sl_mult = 3.0
            
            if c < dn and rsi < 25:
                direction = "long"
                sl_price = c - (a * sl_mult)
                tp_price = sma_val
                if tp_price <= c: tp_price = c + (a * 1.0)
            elif c > up and rsi > 75:
                direction = "short"
                sl_price = c + (a * sl_mult)
                tp_price = sma_val
                if tp_price >= c: tp_price = c - (a * 1.0)"""

content = content.replace(old_logic, new_logic)

with open(filepath, "w") as f:
    f.write(content)

print("Patch applied to 8403 strategy.py")
