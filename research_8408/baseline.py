"""
8408 기준선 — 라이브 DualBB(이중볼린저 역추세)를 그대로 import해 2년 검증한다.

채택 기준 (결과를 보기 전에 확정)
  ① 4분할(각 6개월) 전부 순손익 > 0
  ② 흑자 종목 ≥ 70%
  ③ 이웃 파라미터도 통과 (고립점 배제)
  ④ 총 진입 ≥ 100건
  ⑤ 비관 비용(전부 taker)에서 판정
  ⑥ 8407·8409·8410과 청산 겹침이 낮을 것
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["BT_DATA_DIR"] = "/Users/l/project/8888/research_8409/data"
sys.path.insert(0, "/Users/l/project/8888/research_8407")
sys.path.insert(0, "/Users/l/project/8888/research_8409")

import backtest_8407 as B
B.DATA_DIR = os.environ["BT_DATA_DIR"]
from backtest_8407 import load
from sweep_tf import resample
from portfolio import simulate_portfolio

FIVE = ["SOL/USDT:USDT", "XRP/USDT:USDT", "DOGE/USDT:USDT",
        "ADA/USDT:USDT", "BNB/USDT:USDT"]
SEED = 10.0


class LiveDualBB:
    """라이브 8408 core/strategy.py 를 그대로 감싼다."""

    name = "LIVE-DualBB"

    def __init__(self, tf_label=""):
        sys.path.insert(0, "/Users/l/project/8408")
        from core.strategy import StrategyEngine
        from core.config import CFG
        self.e = StrategyEngine(CFG) if _takes_cfg(StrategyEngine) else StrategyEngine()
        self.cfg = CFG
        self.name = f"LIVE-DualBB{tf_label}"

    def at(self, df, i):
        w = df.iloc[max(0, i - 200):i + 1]
        if len(w) < 60:
            return None
        try:
            s = self.e.generate_signal(w, "BT")
        except Exception:
            return None
        if s is None or s.direction == "none":
            return None

        class S:
            pass
        o = S()
        o.direction = s.direction
        o.atr = float(getattr(s, "atr", 0.0) or 0.0)
        # DualBB는 SL을 스윙 저점, TP를 RR 1:2 절대가격으로 준다
        o.sl_price = float(getattr(s, "swing_sl_price", 0.0) or 0.0)
        o.tp_price = float(getattr(s, "bb_mid", 0.0) or getattr(s, "tp1_price", 0.0) or 0.0)
        o.ref_price = float(getattr(s, "close", 0.0) or 0.0)
        return o


def _takes_cfg(cls):
    import inspect
    try:
        return len(inspect.signature(cls.__init__).parameters) > 1
    except Exception:
        return False


def stat(data, sig, hold, cap=5, notional=5.7):
    tr = sorted(simulate_portfolio(data, sig, hold, max_positions=cap, notional=notional),
                key=lambda x: x["t"])
    if not tr:
        return None
    bal = mn = peak = SEED
    dd = 0.0
    for x in tr:
        bal += x["net"]
        mn = min(mn, bal)
        peak = max(peak, bal)
        dd = max(dd, peak - bal)
    ts = [x["t"] for x in tr]
    parts = [sum(x["net"] for x in tr
                 if ts[len(ts) * k // 4] <= x["t"] <= ts[min(len(ts) - 1, len(ts) * (k + 1) // 4)])
             for k in range(4)]
    bysym = {}
    for x in tr:
        bysym[x["symbol"]] = bysym.get(x["symbol"], 0.0) + x["net"]
    g = sum(x["gross"] for x in tr)
    w = [x for x in tr if x["net"] > 0]
    return {"n": len(tr), "gross": g, "net": sum(x["net"] for x in tr), "bal": bal,
            "mn": mn, "dd": 100 * dd / peak, "parts": parts, "bysym": bysym,
            "pos": sum(1 for v in bysym.values() if v > 0), "nsym": len(bysym),
            "wr": 100 * len(w) / len(tr), "edge": 10000 * g / (len(tr) * notional),
            "trades": tr,
            "ok": all(p > 0 for p in parts) and len(tr) >= 100}


def main():
    raw = {s: load(s) for s in FIVE}
    print("라이브 DualBB(이중볼린저 역추세) 2년 검증 · 5종목 · 상한5 · 비관비용 · 명목가 $5.70")
    print("%-14s %5s %6s %9s %8s %6s %-28s %s"
          % ("타임프레임", "건수", "승률", "순손익", "최저", "낙폭", "4분할", "흑자"))
    for tf, rule, holds in (("1d", "1D", (7, 14, 30)), ("4h", "4h", (12, 42, 90))):
        data = {s: resample(raw[s], rule) for s in FIVE}
        sig = LiveDualBB(f"/{tf}")
        for h in holds:
            r = stat(data, sig, h)
            if r is None:
                print("%-14s 진입 0건" % f"{tf}/H{h}")
                continue
            print("%-14s %5d %5.0f%% %+9.2f %8.2f %5.0f%% %-28s %d/%d %s"
                  % (f"{tf}/H{h}", r["n"], r["wr"], r["net"], r["mn"], r["dd"],
                     " ".join("%+6.2f" % p for p in r["parts"]),
                     r["pos"], r["nsym"], "O" if r["ok"] else "X"))


if __name__ == "__main__":
    main()
