"""승률 개선 필터 검증 — 8402/8401 실거래 33종목, 상승장 돈치안 돌파 기준.

왜 필터인가
  돌파 전략은 **원래 승률이 낮다**(문헌 30~35%). 승률을 억지로 올리면 익절을
  당겨야 하고, 그러면 손익비가 무너져 기대값이 오히려 나빠진다(8410 실측:
  승률 42%인데 손익비 1.14라 손익분기 46.7%를 못 넘음).
  그래서 손익비를 건드리지 않고 **거래 수를 줄여 남는 거래의 질을 높이는**
  진입 필터만 시험한다.

문헌에서 뽑은 후보
  ① ADX 강도      돌파 시점 ADX ≥ 25에서만 진입. 추세가 이미 붙은 장에서만
                  돌파를 취해 횡보 함정을 피한다는 논리.
  ② ATR 버퍼      채널을 0.5 ATR 이상 넘겼을 때만. 1틱 돌파(거짓 돌파) 제거.
  ③ 거래량 강화   현행 >100% 평균 → **>150%**. Zarattini et al.(2024)의
                  'Stocks in Play'는 비정상 거래량 종목 선별이 성과의 대부분을
                  만들었다고 보고했다. 그 아이디어의 단순 이식.
  ④ 이중 채널     빠른 채널(20)과 느린 채널(55)을 함께 봐 방향 일치 시에만.
  ⑤ 돌파 유지     돌파 후 1봉 더 채널 위에서 마감해야 진입(지연 진입).

  ※ 스퀴즈(변동성 압축) 선행조건은 **이미 기각**됐다(횡보 −1387 / 상승 −1252).
    같은 걸 다시 넣지 않는다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사전 합격선 — **결과를 보기 전에 확정한다. 사후 완화 금지.**
  ① 알파가 기준선(현행 돌파+거래량 +951bp)보다 **높을 것**
  ② 기간 4분할 **전부 양수**
  ③ 흑자종목 **70% 이상**
  ④ 신호 **100건 이상** (거래가 너무 줄면 표본이 죽는다)
  ⑤ 승률이 기준선보다 **높을 것** — 이번 목적이 승률이므로 명시적으로 본다
  다섯을 모두 넘겨야 채택한다. 하나라도 미달이면 기각한다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

국면은 BTC 일봉(ADX14+200MA)으로 판정하고 BULL 구간만 본다(8402 실배치와 동일).
진입 i+1봉 시가, 청산 i+1+20봉 시가. 비관비용 왕복 10bp. 미래참조 없음.
"""
import os
import numpy as np
import pandas as pd
import warnings; warnings.filterwarnings("ignore")

import clf33 as C          # load / symbols / adx / btc_regime / sig_donchian 재사용

HOLD = 20
COST_BP = C.COST_BP


def feats(d):
    """필터 판정에 쓰는 지표. 전부 i봉까지의 정보만 쓴다."""
    c, h, l, v = d["close"], d["high"], d["low"], d["volume"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    hi55 = h.rolling(55).max().shift(1)
    lo55 = l.rolling(55).min().shift(1)
    hi20 = h.rolling(20).max().shift(1)
    lo20 = l.rolling(20).min().shift(1)
    vm = v.rolling(20).mean()
    return dict(
        atr=atr, adx=C.adx(d, 14),
        hi55=hi55, lo55=lo55, hi20=hi20, lo20=lo20,
        vol_r=v / vm.replace(0, np.nan),
        # 채널을 얼마나 넘겼나 (ATR 배수)
        over_hi=(c - hi55) / atr.replace(0, np.nan),
        over_lo=(lo55 - c) / atr.replace(0, np.nan),
    )


def build(d):
    """기준선 + 필터 5종. 각 값은 +1(롱)/-1(숏)/0(관망)."""
    f = feats(d)
    base = C.sig_donchian(d, 55)
    volok = (f["vol_r"] > 1.0).fillna(False)
    out = {}
    # 기준선 = 현행 8402 배치 (돌파 + 거래량>평균)
    out["기준선 돌파+거래량"] = base.where(volok, 0)

    adx_ok = (f["adx"] >= 25).fillna(False)
    out["① ADX≥25"] = out["기준선 돌파+거래량"].where(adx_ok, 0)

    buf = ((base > 0) & (f["over_hi"] >= 0.5)) | ((base < 0) & (f["over_lo"] >= 0.5))
    out["② ATR버퍼 0.5"] = out["기준선 돌파+거래량"].where(buf.fillna(False), 0)

    out["③ 거래량>150%"] = base.where((f["vol_r"] > 1.5).fillna(False), 0)

    fast = C.sig_donchian(d, 20)
    out["④ 이중채널 20+55"] = out["기준선 돌파+거래량"].where((fast == base) & (base != 0), 0)

    # 돌파 다음 봉도 채널 위/아래 유지 → 그 봉을 신호로 삼는다(1봉 지연)
    hold_l = (base.shift(1) > 0) & (d["close"] > f["hi55"])
    hold_s = (base.shift(1) < 0) & (d["close"] < f["lo55"])
    s = pd.Series(0, index=d.index)
    s[hold_l] = 1
    s[hold_s] = -1
    out["⑤ 돌파유지 1봉"] = s.where(volok, 0)
    return out


def run():
    reg = C.btc_regime()
    rows = []
    for sym in C.symbols():
        d = C.load(sym)
        if len(d) < 120:
            continue
        op = d["open"].values
        dates = pd.to_datetime(d["date"]).values
        r = np.array([reg.get(x, None) for x in dates], dtype=object)
        cand = build(d)
        fwd = np.full(len(d), np.nan)
        for i in range(len(d) - HOLD - 2):
            e, x = op[i + 1], op[i + 1 + HOLD]
            if e > 0 and x > 0:
                fwd[i] = (x / e - 1) * 10000 - COST_BP
        for i in range(len(d) - HOLD - 2):
            if r[i] != "BULL" or not np.isfinite(fwd[i]):
                continue
            row = {"sym": sym, "date": dates[i + 1], "fwd": fwd[i]}
            for k, v in cand.items():
                row[k] = v.iloc[i]
            rows.append(row)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = run()
    df["q"] = pd.qcut(df["date"].astype("int64"), 4, labels=list("1234"))
    names = [c for c in df.columns if c not in ("sym", "date", "fwd", "q")]

    print("승률 개선 필터 검증 — 33종목 · 상승장(BTC 기준) · 보유 20일 · 비관비용 10bp")
    print("사전 합격선: ①알파 기준선 초과 ②4분할 전부 양수 ③흑자종목 70%↑ ④100건↑ ⑤승률 기준선 초과\n")
    print("  %-18s %8s %7s %7s  %-26s %-8s %s" %
          ("필터", "알파bp", "건수", "승률", "기간4분할", "흑자종목", "판정"))

    base_a = base_w = None
    for k in names:
        sig = df[df[k] != 0]
        n = len(sig)
        if n == 0:
            print("  %-18s %8s %7d" % (k, "-", 0)); continue
        f = lambda g: ((g[g[k] != 0]["fwd"] * g[g[k] != 0][k]).mean() - g["fwd"].mean()
                       if (g[k] != 0).any() else np.nan)
        a = f(df)
        parts = df.groupby("q", observed=True).apply(f)
        bysym = df.groupby("sym").apply(f).dropna()
        pos = int((bysym > 0).sum())
        win = ((sig["fwd"] * sig[k]) > 0).mean() * 100
        if base_a is None:
            base_a, base_w = a, win
            verdict = "기준선"
        else:
            ok = (a > base_a and (parts > 0).all() and len(bysym)
                  and pos / len(bysym) >= 0.7 and n >= 100 and win > base_w)
            miss = "".join(x for x, c in [("①", a > base_a), ("②", (parts > 0).all()),
                                          ("③", pos / len(bysym) >= 0.7 if len(bysym) else False),
                                          ("④", n >= 100), ("⑤", win > base_w)] if not c)
            verdict = "✅ 통과" if ok else "❌ " + miss
        print("  %-18s %+8.0f %7d %6.1f%%  %-26s %2d/%-5d %s" % (
            k, a, n, win, " ".join("%+6.0f" % v for v in parts.values),
            pos, len(bysym), verdict))
    print()
    print("  기준선 대비 — 알파 %+.0fbp · 승률 %.1f%%" % (base_a, base_w))
