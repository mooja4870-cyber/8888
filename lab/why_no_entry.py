#!/usr/bin/env python3
"""why_no_entry.py — 무진입 봇의 원인을 '신호 자체가 없는가 / 차단되는가'로 가른다.

봇 폴더는 **읽기만** 한다(config.json·state 파일). 시세는 거래소 공개 API로
직접 받는다. 봇 프로세스에는 손대지 않는다.

각 봇마다
  ① 차단 요소 점검   AUTO_TRADING · 정지플래그 · 쿨다운 · 포지션 한도
  ② 국면 판정        BTC 일봉 200MA + ADX(14)  → BULL / BEAR / RANGE
  ③ 배정 전략으로 전 종목 평가, **발동까지 남은 거리(%)**를 낸다

거리는 '지금 종가가 문턱까지 몇 % 남았는가'다. 0%면 그 자리가 곧 신호다.
"""
import asyncio
import json
import os
import sys
import datetime as dt

import numpy as np
import pandas as pd
import ccxt.async_support as ccxt

BOTS = sys.argv[1:] or ["8401", "8402", "8410"]
ROOT = "/Users/l/project"


def cfg_of(bot):
    with open(f"{ROOT}/{bot}/config.json", encoding="utf-8") as f:
        return json.load(f)


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


async def ohlcv(ex, sym, limit):
    raw = await ex.fetch_ohlcv(sym, timeframe="1d", limit=limit)
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    return df


def regime_of(df, ma_len=200, adx_len=14, th=20.0):
    d = df.iloc[:-1]                      # 미완성 현재봉 제외 (봇과 동일)
    ma = d["close"].rolling(ma_len).mean()
    adx = _adx(d, adx_len)
    c, m, a = float(d["close"].iloc[-1]), float(ma.iloc[-1]), float(adx.iloc[-1])
    reg = "RANGE" if a < th else ("BULL" if c > m else "BEAR")
    detail = f"BTC 종가 {c:,.0f} vs {ma_len}MA {m:,.0f} ({(c/m-1)*100:+.2f}%) · ADX {a:.1f} {'≥' if a>=th else '<'} {th:.0f}"
    return reg, detail


def eval_donchian(df, c, vol_req, vol_mult, vol_len):
    """반환: (신호방향|None, 롱까지 남은 %, 숏까지 남은 %, 부가설명)"""
    n = c["DON_LEN"]
    d = df.iloc[:-1]
    hi = d["high"].rolling(n).max().shift(1)
    lo = d["low"].rolling(n).min().shift(1)
    px = float(d["close"].iloc[-1])
    h_ref, l_ref = float(hi.iloc[-1]), float(lo.iloc[-1])
    if not (np.isfinite(h_ref) and np.isfinite(l_ref)) or px <= 0:
        return None, None, None, "지표 미확정"
    up_gap = (h_ref / px - 1) * 100      # 롱까지 올라야 할 %
    dn_gap = (px / l_ref - 1) * 100      # 숏까지 내려야 할 %
    vol_ok = True
    note = ""
    if vol_req:
        vm = d["volume"].rolling(vol_len).mean()
        vol_ok = bool(np.isfinite(vm.iloc[-1]) and d["volume"].iloc[-1] > vm.iloc[-1] * vol_mult)
        note = f"거래량 {'OK' if vol_ok else '미달'}"
    sig = None
    if px > h_ref:
        sig = "long" if vol_ok else None
    elif px < l_ref:
        sig = "short" if vol_ok else None
    return sig, up_gap, dn_gap, note


def eval_dualbb(df, c):
    n = c.get("DBB_LEN", 20)
    k1 = c.get("DBB_K1", 1.0)
    k2 = c.get("DBB_K2", 2.0)
    d = df.iloc[:-1]
    close = d["close"]
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    px = float(close.iloc[-1])
    m, s = float(mid.iloc[-1]), float(sd.iloc[-1])
    if not np.isfinite(m) or not np.isfinite(s) or s <= 0 or px <= 0:
        return None, None, None, "지표 미확정"
    u1, u2, l1, l2 = m + k1 * s, m + k2 * s, m - k1 * s, m - k2 * s
    sig = None
    if u1 < px <= u2:
        sig = "long"
    elif l2 <= px < l1:
        sig = "short"
    up_gap = (u1 / px - 1) * 100          # 롱 구역 진입까지 올라야 할 %
    dn_gap = (px / l1 - 1) * 100          # 숏 구역 진입까지 내려야 할 %
    zone = "2SD 밖 과열" if (px > u2 or px < l2) else "중앙구역"
    return sig, up_gap, dn_gap, f"{zone} · 중심대비 {(px/m-1)*100:+.2f}%"


async def run_bot(bot):
    c = cfg_of(bot)
    ex_id = c.get("EXCHANGE_ID", "okx")
    syms = c.get("SYMBOL_WHITELIST") or []
    print(f"\n{'='*74}\n  {bot}  ({ex_id.upper()})\n{'='*74}")

    # ── ① 차단 요소 ──────────────────────────────────────────────
    rt = jload(f"{ROOT}/{bot}/data/bot_runtime.json", {})
    st = jload(f"{ROOT}/{bot}/data/stats.json", {})
    pos = jload(f"{ROOT}/{bot}/data/active_positions.json", {}) or {}
    auto = c.get("AUTO_TRADING")
    print("  ① 차단 요소")
    print(f"     AUTO_TRADING(config.json) = {auto}")
    print(f"     trading_enabled(실행중)   = {rt.get('trading_enabled')}")
    print(f"     연속손절 정지 플래그      = {st.get('halted_by_consec_sl')}")
    print(f"     글로벌 쿨다운             = {st.get('global_cooldown_until')}")
    print(f"     보유 포지션               = {len(pos)}건 / 한도 {c.get('MAX_POSITIONS')}")
    hb = rt.get("last_heartbeat")
    print(f"     하트비트                  = {hb}")
    if auto is False or rt.get("trading_enabled") is False:
        print("     ❌ 자동매매 OFF — 신호가 나도 진입하지 않는다")

    ex = getattr(ccxt, ex_id)({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    try:
        # ── ② 국면 ────────────────────────────────────────────────
        ref = c.get("REGIME_REF_SYMBOL", "BTC/USDT:USDT")
        btc = await ohlcv(ex, ref, 260)
        reg, detail = regime_of(
            btc,
            int(c.get("REGIME_MA_LEN", 200)),
            int(c.get("REGIME_ADX_LEN", 14)),
            float(c.get("REGIME_ADX_THRESHOLD", 20.0)),
        )
        smap = c.get("REGIME_STRATEGY_MAP") or {
            "BULL": "Donchian", "BEAR": "DualBB", "RANGE": "DonchianVol"}
        strat = smap.get(reg, "DonchianVol")
        kr = {"BULL": "상승추세", "BEAR": "하락추세", "RANGE": "횡보"}[reg]
        print(f"\n  ② 국면 = {reg}({kr}) → 배정 전략 **{strat}**")
        print(f"     {detail}")

        # ── ③ 종목별 발동 거리 ─────────────────────────────────────
        don_len = int(c.get("DON_LEN", 55))
        need = max(don_len + 40, 120)
        rows = []
        for s in syms:
            try:
                df = await ohlcv(ex, s, need)
            except Exception as e:
                rows.append((s, None, None, None, f"조회실패 {str(e)[:30]}"))
                continue
            if len(df) < 40:
                rows.append((s, None, None, None, f"데이터 {len(df)}봉"))
                continue
            if strat in ("Donchian", "DonchianVol"):
                sig, u, d_, note = eval_donchian(
                    df, {"DON_LEN": don_len},
                    strat == "DonchianVol",
                    float(c.get("DON_VOL_MULT", 1.0)),
                    int(c.get("DON_VOL_LEN", 20)))
            else:
                sig, u, d_, note = eval_dualbb(df, c)
            rows.append((s, sig, u, d_, note))

        hits = [r for r in rows if r[1]]
        valid = [r for r in rows if r[2] is not None]
        print(f"\n  ③ {len(syms)}종목 평가 · 신호 {len(hits)}개")
        if hits:
            for s, sig, u, d_, note in hits:
                print(f"     ✅ {s:22} {sig.upper():5} {note}")
        if valid:
            # 발동까지 가장 가까운 쪽(롱/숏 중 작은 값)으로 정렬
            near = sorted(valid, key=lambda r: min(r[2], r[3]))
            ups = [r[2] for r in valid]
            dns = [r[3] for r in valid]
            print(f"     롱 발동까지 중앙값 +{np.median(ups):.2f}%  ·  "
                  f"숏 발동까지 중앙값 −{np.median(dns):.2f}%")
            print("     ── 발동에 가장 가까운 5종목 ──")
            for s, sig, u, d_, note in near[:5]:
                side = "롱" if u <= d_ else "숏"
                gap = min(u, d_)
                print(f"       {s:22} {side} 까지 {gap:+6.2f}%   (롱 +{u:.2f}% / 숏 −{d_:.2f}%)")
    finally:
        await ex.close()


async def main():
    print(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "  무진입 원인 진단")
    for b in BOTS:
        try:
            await run_bot(b)
        except Exception as e:
            print(f"\n  {b} 진단 실패: {e}")


if __name__ == "__main__":
    asyncio.run(main())
