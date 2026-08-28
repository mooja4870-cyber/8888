"""
Binance 공식 공개 아카이브(data.binance.vision)에서 15m 봉을 받아온다.

REST API는 레이트리밋 때문에 히스토리 수집이 사실상 불가능하다
(Binance 봇 4대가 같은 IP를 공유해 418 밴이 반복됨).
아카이브는 같은 원본 데이터를 정적 파일로 제공하며 레이트리밋이 없다.

  monthly/klines/{SYMBOL}/15m/{SYMBOL}-15m-YYYY-MM.zip
  daily/klines/{SYMBOL}/15m/{SYMBOL}-15m-YYYY-MM-DD.zip   (당월 보충용)
"""
import io
import os
import sys
import zipfile
import urllib.request
from datetime import date, timedelta

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("BT_DATA_DIR", os.path.join(HERE, "data"))
BASE = "https://data.binance.vision/data/futures/um"

# 8409는 8407과 겹치지 않는 구성을 찾아야 하므로 종목 후보를 넓혀 둔다.
PAIRS = {
    "SOL/USDT:USDT":  "SOLUSDT",
    "ETH/USDT:USDT":  "ETHUSDT",
    "XRP/USDT:USDT":  "XRPUSDT",
    "DOGE/USDT:USDT": "DOGEUSDT",
    "BNB/USDT:USDT":  "BNBUSDT",
    "ADA/USDT:USDT":  "ADAUSDT",
    "AVAX/USDT:USDT": "AVAXUSDT",
    "LINK/USDT:USDT": "LINKUSDT",
    "LTC/USDT:USDT":  "LTCUSDT",
    "BTC/USDT:USDT":  "BTCUSDT",
}

COLS = ["timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "tb_base", "tb_quote", "ignore"]


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()
    except Exception:
        return None


def _parse(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            head = f.readline()
            f.seek(0)
            # 2025년 이후 파일에는 헤더 행이 있다
            skip = 1 if head.startswith(b"open_time") else 0
            return pd.read_csv(f, header=None, names=COLS, skiprows=skip)


def fetch(symbol, months):
    ticker = PAIRS[symbol]
    frames = []
    today = date.today()

    for k in range(months, 0, -1):
        y, m = today.year, today.month - k
        while m <= 0:
            m += 12
            y -= 1
        url = f"{BASE}/monthly/klines/{ticker}/15m/{ticker}-15m-{y}-{m:02d}.zip"
        raw = _get(url)
        if raw:
            frames.append(_parse(raw))
            print(f"    월 {y}-{m:02d}")

    # 당월은 월별 파일이 아직 없으므로 일별로 보충
    d = today.replace(day=1)
    while d < today:
        url = f"{BASE}/daily/klines/{ticker}/15m/{ticker}-15m-{d.isoformat()}.zip"
        raw = _get(url)
        if raw:
            frames.append(_parse(raw))
        d += timedelta(days=1)

    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df = df.drop_duplicates("timestamp").sort_values("timestamp")
    # 아카이브는 마이크로초 단위로 바뀐 시기가 있어 자릿수로 판별한다
    unit = "us" if df["timestamp"].iloc[-1] > 1e14 else "ms"
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit=unit)
    return df.reset_index(drop=True)


if __name__ == "__main__":
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    os.makedirs(DATA_DIR, exist_ok=True)
    for sym in PAIRS:
        print(f"  {sym}")
        df = fetch(sym, months)
        if df is None:
            print("    실패")
            continue
        p = os.path.join(DATA_DIR, sym.replace("/", "_").replace(":", "_") + ".csv")
        df.to_csv(p, index=False)
        print(f"    → {len(df)}봉  {df.timestamp.iloc[0]} ~ {df.timestamp.iloc[-1]}")
