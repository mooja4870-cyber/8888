"""
8407 백테스트 하네스 — 라이브 전략을 그대로 재현해 변형안을 비교한다.

원칙
  · 라이브 코드(core/strategy.py)를 직접 import 한다. 로직을 베끼지 않는다.
  · 라이브 데이터 파일(config.json / trade_history.csv / *_state.json)을 절대 쓰지 않는다.
  · 수수료는 명목가(레버리지 포함) 기준으로 매 체결마다 부과한다.
  · 실거래와 같은 종목군(SOL·ETH·XRP·DOGE)에서만 판정한다.

사용법
    python3 backtest_8407.py fetch     # 과거 15m 봉 수집 → data/*.csv
    python3 backtest_8407.py run       # 변형안 비교 실행
"""
import os
import sys
import json
import asyncio
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

BOT_DIR = "/Users/l/project/8407"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

SYMBOLS = ["SOL/USDT:USDT", "ETH/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT"]
TIMEFRAME = "15m"
BARS_PER_HOUR = 4

# Binance USDⓈ-M 선물 요율 (실체결 기록으로 taker 0.0500% 검증됨)
FEE_TAKER = 0.0005
FEE_MAKER = 0.0002


# ────────────────────────────────────────────────────────────────
# 데이터 수집
# ────────────────────────────────────────────────────────────────
async def fetch():
    sys.path.insert(0, BOT_DIR)
    os.chdir(BOT_DIR)
    from dotenv import load_dotenv
    from core.api_keys import load_api_keys
    load_dotenv(override=True)
    load_api_keys(override=True)
    import ccxt.async_support as ccxt

    ex = ccxt.binance({
        "apiKey": os.getenv("BINANCE_API_KEY", ""),
        "secret": os.getenv("BINANCE_SECRET_KEY", ""),
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })
    await ex.load_markets()
    os.makedirs(DATA_DIR, exist_ok=True)

    # Binance는 한 번에 1000봉까지 준다. 과거로 거슬러 since를 밀어 넣어 이어붙인다.
    # Binance 봇 4대가 같은 IP를 쓰므로 호출 간격을 넉넉히 둔다(418 밴 방지).
    days = int(os.environ.get("BT_DAYS", "90"))
    bar_ms = 15 * 60 * 1000
    total = days * 24 * 4
    calls = (total // 1000) + 1
    now_ms = ex.milliseconds()

    for sym in SYMBOLS:
        frames = []
        since = now_ms - total * bar_ms
        for _ in range(calls):
            batch = await ex.fetch_ohlcv(sym, TIMEFRAME, since=since, limit=1000)
            if not batch:
                break
            frames.append(batch)
            nxt = batch[-1][0] + bar_ms
            if nxt <= since or batch[-1][0] >= now_ms - bar_ms:
                break
            since = nxt
            await asyncio.sleep(2.0)
        rows = [r for b in frames for r in b]
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df = df.drop_duplicates("timestamp").sort_values("timestamp")
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        path = os.path.join(DATA_DIR, sym.replace("/", "_").replace(":", "_") + ".csv")
        df.to_csv(path, index=False)
        print(f"  {sym:20s} {len(df):5d}봉  {df.timestamp.iloc[0]} ~ {df.timestamp.iloc[-1]}")

    await ex.close()


def load(sym):
    path = os.path.join(DATA_DIR, sym.replace("/", "_").replace(":", "_") + ".csv")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df.reset_index(drop=True)


# ────────────────────────────────────────────────────────────────
# 변형안 정의
# ────────────────────────────────────────────────────────────────
@dataclass
class Variant:
    name: str
    prob_threshold: float = 0.55
    sl_atr: float = 2.0
    tp_atr: float = 4.0
    timeout_bars: int = 3           # 45분 = 15m×3. 0이면 타임아웃 청산 없음
    max_hold_bars: int = 24         # MAX_HOLDING_HOURS 6.0
    entry_fee: float = FEE_TAKER
    exit_fee: float = FEE_TAKER
    # TP를 지정가(reduceOnly)로 걸면 호가에 얹혀 있다가 체결되므로 메이커다.
    # SL은 스톱마켓이라 테이커를 피할 수 없다(안전상 지정가로 바꾸면 안 된다).
    tp_exit_fee: float = None       # None이면 exit_fee를 그대로 쓴다
    mean_reversion: bool = False    # 부가전략: 평균회귀 오버레이


# ────────────────────────────────────────────────────────────────
# 신호 — 라이브 core/strategy.py 를 그대로 사용
# ────────────────────────────────────────────────────────────────
class LiveSignal:
    """라이브 StrategyEngine을 감싸, 봉 단위로 신호를 뽑는다."""

    def __init__(self, threshold, sl_atr, tp_atr):
        sys.path.insert(0, BOT_DIR)
        from core.strategy import StrategyEngine

        class Cfg:
            DL_MODEL_PATH = "model/sol_directional.onnx"
            DL_LOOKBACK_BARS = 60
            DL_PROB_THRESHOLD = threshold
            DL_SL_ATR_MULT = sl_atr
            DL_TP_ATR_MULT = tp_atr

        self.engine = StrategyEngine(Cfg())

    def at(self, df, i):
        """i번째 봉 종가 시점의 신호. 미래 데이터를 보지 않는다."""
        window = df.iloc[max(0, i - 120):i + 1]
        if len(window) < 60:
            return None
        return self.engine.generate_signal(window, "BT")


def mean_reversion_ok(df, i, direction):
    """부가전략: 볼린저 극단에서의 역방향 진입만 허용.

    문헌 근거 — 모멘텀과 평균회귀는 국면 보완적이며, 단순 혼합만으로도
    Sharpe가 개선된다(Medium/systematic-crypto, arXiv:2105.13727).
    여기서는 '평균회귀와 배치되는 모멘텀 신호를 거른다'는 소극적 형태로 적용한다.
    """
    w = df["close"].iloc[max(0, i - 20):i + 1].values
    if len(w) < 20:
        return True
    sma, sd = w.mean(), w.std()
    if sd == 0:
        return True
    z = (w[-1] - sma) / sd
    # 상단 과열(z>1.5)에서 롱 금지, 하단 과매도(z<-1.5)에서 숏 금지
    if direction == "long" and z > 1.5:
        return False
    if direction == "short" and z < -1.5:
        return False
    return True


# ────────────────────────────────────────────────────────────────
# 시뮬레이션
# ────────────────────────────────────────────────────────────────
def simulate(df, v: LiveSignal, cfg: Variant, notional=7.0):
    """한 종목을 처음부터 끝까지 재생. 동시 보유는 1건으로 제한.

    df.iloc[i]는 봉마다 Series를 만들어 20k봉에서 병목이 된다.
    값 접근은 numpy 배열로 하고, 신호 함수에만 df를 넘긴다.
    """
    a_high = df["high"].values.astype(float)
    a_low = df["low"].values.astype(float)
    a_close = df["close"].values.astype(float)
    a_open = df["open"].values.astype(float)

    trades = []
    pos = None

    for i in range(60, len(df) - 1):
        if pos is not None:
            held = i - pos["i"]
            hi, lo = a_high[i], a_low[i]

            exit_px, kind = None, None
            # 같은 봉에서 SL·TP가 모두 닿으면 보수적으로 SL을 먼저 잡는다
            if pos["dir"] == "long":
                if lo <= pos["sl"]:
                    exit_px, kind = pos["sl"], "SL"
                elif hi >= pos["tp"]:
                    exit_px, kind = pos["tp"], "TP"
            else:
                if hi >= pos["sl"]:
                    exit_px, kind = pos["sl"], "SL"
                elif lo <= pos["tp"]:
                    exit_px, kind = pos["tp"], "TP"

            if exit_px is None and cfg.timeout_bars and held >= cfg.timeout_bars:
                px = a_close[i]
                pnl_pct = (px / pos["px"] - 1) * (1 if pos["dir"] == "long" else -1)
                if pnl_pct <= 0:                      # TIMEOUT_SKIP_PROFITABLE=true
                    exit_px, kind = px, "TIMEOUT"

            if exit_px is None and held >= cfg.max_hold_bars:
                exit_px, kind = a_close[i], "MAXHOLD"

            if exit_px is not None:
                r = (exit_px / pos["px"] - 1) * (1 if pos["dir"] == "long" else -1)
                gross = notional * r
                xf = cfg.exit_fee
                if kind == "TP" and cfg.tp_exit_fee is not None:
                    xf = cfg.tp_exit_fee
                fee = notional * (cfg.entry_fee + xf)
                trades.append({"kind": kind, "ret": r, "gross": gross,
                               "fee": fee, "net": gross - fee})
                pos = None
            continue

        sig = v.at(df, i)
        if sig is None or sig.direction == "none":
            continue
        if cfg.mean_reversion and not mean_reversion_ok(df, i, sig.direction):
            continue

        entry = a_open[i + 1]                   # 다음 봉 시가 체결 (look-ahead 방지)
        atr = sig.atr
        if atr <= 0:
            continue
        if sig.direction == "long":
            sl, tp = entry - atr * cfg.sl_atr, entry + atr * cfg.tp_atr
        else:
            sl, tp = entry + atr * cfg.sl_atr, entry - atr * cfg.tp_atr
        pos = {"i": i, "px": entry, "dir": sig.direction, "sl": sl, "tp": tp}

    return trades


def report(name, all_trades):
    if not all_trades:
        print(f"{name:28s}  진입 0건")
        return None
    net = [t["net"] for t in all_trades]
    gross = sum(t["gross"] for t in all_trades)
    fee = sum(t["fee"] for t in all_trades)
    wins = [x for x in net if x > 0]
    from collections import Counter
    kinds = Counter(t["kind"] for t in all_trades)
    print(f"{name:28s}  {len(net):4d}건 | 총이익 {gross:+.3f} | 수수료 -{fee:.3f} | "
          f"순손익 {sum(net):+.3f} | 승률 {100*len(wins)/len(net):4.1f}% | "
          f"{dict(kinds)}")
    return sum(net)


def run():
    variants = [
        Variant("A 기준선(현행)"),
        Variant("B 타임아웃 제거", timeout_bars=0),
        Variant("C 진입 maker", entry_fee=FEE_MAKER),
        Variant("D B+C", timeout_bars=0, entry_fee=FEE_MAKER),
        Variant("E D+평균회귀필터", timeout_bars=0, entry_fee=FEE_MAKER, mean_reversion=True),
    ]
    # 임계값 스윕 — 특정 값 하나만 좋다면 과최적화를 의심해야 한다.
    # 타임아웃은 유지(B가 기준선보다 나빴다)하고 maker만 적용한 위에서 훑는다.
    for th in (0.55, 0.58, 0.60, 0.62, 0.65, 0.70):
        variants.append(Variant(f"T 임계{th:.2f}", entry_fee=FEE_MAKER, prob_threshold=th))

    # IP 레이트리밋으로 일부 종목만 받았을 수 있다. 있는 것만 쓰고 무엇을 썼는지 밝힌다.
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = load(s)
        except FileNotFoundError:
            print(f"  [미수집] {s} — 이번 판정에서 제외")
    if not data:
        print("데이터 없음. fetch 먼저 실행.")
        return
    k0 = next(iter(data))
    print(f"기간: {data[k0].timestamp.iloc[0]} ~ {data[k0].timestamp.iloc[-1]}")
    print(f"봉수: {len(data[k0])}  종목: {len(data)}/{len(SYMBOLS)} {list(data)}\n")

    results = {}
    per_symbol = {}
    for cfg in variants:
        sig = LiveSignal(cfg.prob_threshold, cfg.sl_atr, cfg.tp_atr)
        allt = []
        bysym = {}
        for s in data:
            t = simulate(data[s], sig, cfg)
            bysym[s] = sum(x["net"] for x in t)
            allt += t
        per_symbol[cfg.name] = bysym
        results[cfg.name] = report(cfg.name, allt)

    base = results.get("A 기준선(현행)")
    if base:
        print("\n기준선 대비:")
        for k, v_ in results.items():
            if v_ is not None and k != "A 기준선(현행)":
                print(f"  {k:28s} {v_ - base:+.3f} USDT ({100*(v_-base)/abs(base):+.0f}%)")

    # 종목분산 강건성 — 한 종목이 전체 결과를 끌고 가면 가짜 엣지를 의심해야 한다
    print("\n종목별 순손익:")
    for k, bysym in per_symbol.items():
        print(f"  {k:28s} " + "  ".join(f"{s.split('/')[0]}:{v_:+.3f}" for s, v_ in bysym.items()))


class ReversionSignal:
    """부가전략: 볼린저 z-score 역방향 진입 (독립 전략).

    문헌 근거 — 모멘텀과 평균회귀는 국면 보완적이며, 두 알파를 함께 굴리면
    개별 전략보다 매끄러운 수익을 낸다(Systematic Crypto Trading Strategies;
    arXiv:2105.13727 Slow Momentum with Fast Reversion).
    여기서는 '거르는 필터'가 아니라 '독립적으로 진입하는' 형태로 구현해
    기저 모멘텀 신호와 별개로 엣지가 있는지 본다.
    """

    def __init__(self, z_entry=2.0, sl_atr=2.0, tp_atr=4.0, period=20):
        self.z, self.sl_atr, self.tp_atr, self.p = z_entry, sl_atr, tp_atr, period

    def at(self, df, i):
        w = df.iloc[max(0, i - self.p + 1):i + 1]
        if len(w) < self.p:
            return None
        c = w["close"].values
        sma, sd = c.mean(), c.std()
        if sd == 0:
            return None
        z = (c[-1] - sma) / sd

        h, l, cl = df["high"].values[:i + 1], df["low"].values[:i + 1], df["close"].values[:i + 1]
        if len(cl) < 15:
            return None
        tr = np.maximum(h[1:] - l[1:], np.abs(h[1:] - cl[:-1]))
        atr = float(np.mean(tr[-14:]))
        if atr <= 0:
            return None

        if z <= -self.z:
            d = "long"
        elif z >= self.z:
            d = "short"
        else:
            return None

        class S:
            pass
        s = S()
        s.direction, s.atr = d, atr
        return s


def reversion():
    """부가전략 단독 검증 — 기간분할·종목분산을 함께 본다."""
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = load(s)
        except FileNotFoundError:
            pass
    k0 = next(iter(data))
    mid = len(data[k0]) // 2

    for zi in (1.5, 2.0, 2.5):
        sig = ReversionSignal(z_entry=zi)
        cfg = Variant(f"MR z={zi}", timeout_bars=0, entry_fee=FEE_MAKER)
        print(f"역방향 진입 z={zi}")
        for hi, label in ((0, "전반"), (1, "후반")):
            allt, bysym = [], {}
            for s, df in data.items():
                part = (df.iloc[:mid] if hi == 0 else df.iloc[mid:]).reset_index(drop=True)
                t = simulate(part, sig, cfg)
                bysym[s] = sum(x["net"] for x in t)
                allt += t
            tot = sum(x["net"] for x in allt)
            pos = sum(1 for v_ in bysym.values() if v_ > 0)
            detail = "  ".join(f"{s.split('/')[0]}:{v_:+.2f}" for s, v_ in bysym.items())
            print(f"   {label} {tot:+7.3f} USDT ({len(allt):3d}건, 흑자 {pos}/{len(bysym)})  {detail}")
        print()


def robust():
    """기간분할 강건성 — 전 구간에서 좋아 보여도 한쪽 반이 캐리하면 가짜 엣지다."""
    cands = [
        Variant("A 기준선(현행)"),
        Variant("C 진입 maker", entry_fee=FEE_MAKER),
        Variant("D 타임아웃제거+maker", timeout_bars=0, entry_fee=FEE_MAKER),
    ]
    data = {}
    for s in SYMBOLS:
        try:
            data[s] = load(s)
        except FileNotFoundError:
            pass

    halves = {}
    for s, df in data.items():
        mid = len(df) // 2
        halves[s] = (df.iloc[:mid].reset_index(drop=True),
                     df.iloc[mid:].reset_index(drop=True))

    k0 = next(iter(data))
    m = len(data[k0]) // 2
    print(f"전반: {data[k0].timestamp.iloc[0]} ~ {data[k0].timestamp.iloc[m-1]}")
    print(f"후반: {data[k0].timestamp.iloc[m]} ~ {data[k0].timestamp.iloc[-1]}\n")

    for cfg in cands:
        sig = LiveSignal(cfg.prob_threshold, cfg.sl_atr, cfg.tp_atr)
        out = []
        for hi, label in ((0, "전반"), (1, "후반")):
            allt, bysym = [], {}
            for s in data:
                t = simulate(halves[s][hi], sig, cfg)
                bysym[s] = sum(x["net"] for x in t)
                allt += t
            tot = sum(x["net"] for x in allt)
            pos = sum(1 for v_ in bysym.values() if v_ > 0)
            out.append((label, tot, len(allt), pos, bysym))
        print(f"{cfg.name}")
        for label, tot, n, pos, bysym in out:
            detail = "  ".join(f"{s.split('/')[0]}:{v_:+.2f}" for s, v_ in bysym.items())
            print(f"   {label} {tot:+7.3f} USDT ({n:3d}건, 흑자종목 {pos}/{len(bysym)})  {detail}")
        print()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "fetch":
        asyncio.run(fetch())
    elif cmd == "reversion":
        reversion()
    elif cmd == "robust":
        robust()
    else:
        run()
