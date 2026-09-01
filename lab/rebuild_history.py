"""
거래이력 CSV 복구 — 짝을 못 찾는 청산('진입유실')을 거래소 실측 체결로 되살린다.

왜 필요한가
  trade_history.csv에서 진입 기록이 사라지거나(8403: 청산 4행만 남고 전멸)
  방향 컬럼이 깨지면(8407: 방향='long', 체결ID 없음) 짝맞춤이 실패한다.
  실패한 청산은 status가 '청산 완료 (진입유실)'이 되는데, 엔진의
  5전 3패 매매방향 스위칭은 status == '청산 완료'만 세므로 **판정 자체가 죽는다.**
  손익 집계도 함께 어긋난다.

방식 — 추정값을 만들지 않는다
  ① 현재 CSV로 짝맞춤을 돌려 '진입유실'이 나는 종목을 찾는다
  ② 그 종목의 체결을 거래소에서 받는다 (category 필드가 진입/청산을 직접 알려준다)
  ③ 거래소 체결이 덮는 시간구간 [t_min, t_max] 안의 CSV 행만 버리고 실측으로 갈아끼운다
     → 구간 밖(거래소가 더는 주지 않는 옛 기록)은 건드리지 않아 유실이 없다
  ④ 다시 짝맞춤을 돌려 '진입유실'이 사라졌는지 확인한다

  python3 rebuild_history.py <봇번호> [--apply]      # --apply 없으면 점검만
"""
import asyncio
import csv
import os
import shutil
import sys
import time
from collections import Counter

COLS = ["시간", "심볼", "유형", "방향", "가격", "수량", "수익(USDT)", "수익률(%)",
        "청산유형", "레버리지", "주문ID", "체결ID", "수수료(USDT)", "매매모드"]


def _enter(bot):
    """봇 폴더를 import 경로로 세운다. core.* 캐시는 봇마다 비운다."""
    d = f"/Users/l/project/{bot}"
    for m in [k for k in sys.modules if k == "core" or k.startswith("core.")]:
        del sys.modules[m]
    os.chdir(d)
    sys.path.insert(0, d)
    return d


def _pairs(bot):
    from core.history_helper import load_local_trade_history, aggregate_and_pair_trades
    raw = load_local_trade_history()
    return raw, aggregate_and_pair_trades(raw)


def _lost_symbols(paired):
    return sorted({p["symbol"] for p in paired
                   if "진입유실" in str(p.get("status", ""))})


async def _fills(bot, symbols, since_ms=None):
    """거래소 실측 체결.

    since_ms를 주면 그 시각부터 직접 조회한다. get_trade_history()는 since를
    넘길 수 없어 '최근 체결'만 돌려주는데, 짝을 잃은 청산이 몇 주 전이면
    그 창 밖이라 진입을 영영 못 찾는다(8409 PROM·TRUMP가 그랬다).
    """
    import core.exchange as EX
    from core.config import CFG
    ex_id = str(getattr(CFG, "EXCHANGE_ID", "")).lower()
    pre = "BINANCE" if ex_id == "binance" else "OKX"
    Client = getattr(EX, "BinanceClient", None) if pre == "BINANCE" else None
    Client = Client or getattr(EX, "OKXClient")
    c = Client(os.getenv(f"{pre}_API_KEY", ""), os.getenv(f"{pre}_SECRET_KEY", ""),
               os.getenv(f"{pre}_PASSPHRASE", ""))
    out = {}
    try:
        await c.load_markets()
        for s in symbols:
            try:
                got = await c.get_trade_history(s, limit=200) or []
                sm = (since_ms or {}).get(s)
                if sm:
                    # 원시 ccxt로 since 지정 조회 후, 봇 스키마로 정규화된 것과 합친다
                    raw = await c.exchange.fetch_my_trades(s, sm, 1000)
                    have = {str(x.get("trade_id") or x.get("id") or "") for x in got}
                    for r in raw:
                        if str(r.get("id")) in have:
                            continue
                        info = r.get("info", {}) if isinstance(r.get("info"), dict) else {}
                        rp = info.get("realizedPnl", info.get("fillPnl"))
                        rp = float(rp) if rp not in (None, "") else 0.0
                        # 봇의 exchange.py와 같은 기준으로 진입/청산을 가른다.
                        # 손익이 0인 본전 청산도 있어 posSide 조건을 함께 본다.
                        ps = str(info.get("positionSide", info.get("posSide", ""))).upper()
                        sd = str(r.get("side", "")).lower()
                        is_close = (rp != 0.0) or (ps == "LONG" and sd == "sell") \
                            or (ps == "SHORT" and sd == "buy")
                        got.append({
                            "timestamp": r.get("timestamp"), "symbol": s,
                            "category": "청산" if is_close else "진입",
                            "side": r.get("side"), "price": r.get("price"),
                            "amount": r.get("amount"), "pnl": rp, "pnl_pct": 0.0,
                            "order_id": r.get("order"), "id": r.get("id"),
                            "fee": (r.get("fee") or {}).get("cost", 0.0),
                        })
                out[s] = got
            except Exception as e:
                print(f"     ✗ {s} 체결 조회 실패: {str(e)[:50]}")
                out[s] = []
            await asyncio.sleep(0.4)          # 레이트리밋 여유
    finally:
        await c.close()
    return out


def _ts_str(v):
    """CSV의 '시간' 문자열로 변환. Timestamp면 그대로, epoch ms면 KST(+9)."""
    from datetime import datetime, timedelta, timezone
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, (int, float)) and v > 0:
        sec = v / 1000.0 if v > 1e10 else v
        return (datetime.fromtimestamp(sec, timezone.utc)
                + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:19]


def _row(f, lev, mode):
    """거래소 체결 1건 → CSV 한 행. 없는 값은 추정하지 않고 공란으로 둔다."""
    return [
        _ts_str(f.get("timestamp")),
        f.get("symbol", ""),
        f.get("category", ""),                      # 진입 / 청산 (거래소가 알려준 값)
        f.get("side", ""),
        f.get("price", 0),
        f.get("amount", 0),
        round(float(f.get("pnl") or 0.0), 6),
        round(float(f.get("pnl_pct") or 0.0), 6),
        "",                                          # 청산유형은 거래소가 모른다
        lev,
        f"ID_{f.get('order_id', '')}",
        # 체결ID 키 이름이 봇마다 다르다(8407='id', 8409='trade_id'). 둘 다 본다 —
        # 공란으로 들어가면 _dedupe_trades와 log_trade의 중복차단이 무력해진다.
        f.get("trade_id") or f.get("id") or "",
        abs(float(f.get("fee") or 0.0)),
        mode,
    ]


def rebuild(bot, apply=False):
    cwd = os.getcwd()
    saved = list(sys.path)
    try:
        d = _enter(bot)
        from dotenv import load_dotenv
        from core.api_keys import load_api_keys
        load_dotenv(override=True)
        load_api_keys(override=True)
        from core.config import CFG
        from core import logger as L

        path = L.LOG_FILE
        raw, paired = _pairs(bot)
        lost = _lost_symbols(paired)
        before = Counter(p.get("status") for p in paired)
        print(f"[{bot}] 체결 {len(raw)} → 짝맞춤 {len(paired)} · {dict(before)}")
        if not lost:
            print("     진입유실 없음 — 손댈 것 없음")
            return
        print(f"     진입유실 종목 {len(lost)}개: {', '.join(s.split('/')[0] for s in lost)}")
        if not apply:
            print("     (점검 모드 — 고치려면 --apply)")
            return

        # 짝을 잃은 청산 중 가장 오래된 시각 - 30일부터 조회한다.
        # 3일로 잡았더니 8401 SOL의 진입이 그보다 앞서 있어 끝내 못 찾았다.
        # 진입은 청산보다 임의로 오래 앞설 수 있으므로 넉넉히 잡는다.
        import pandas as _pd
        since_ms = {}
        for s in lost:
            ts = [_pd.to_datetime(str(p.get("exit_time")), errors="coerce")
                  for p in paired
                  if p["symbol"] == s and "진입유실" in str(p.get("status", ""))]
            ts = [t for t in ts if _pd.notna(t)]
            if ts:
                since_ms[s] = int((min(ts) - _pd.Timedelta(days=30)).timestamp() * 1000)

        fills = asyncio.run(_fills(bot, lost, since_ms))
        lev = int(getattr(CFG, "LEVERAGE", 3))
        mode = "역방향" if getattr(CFG, "USE_BLUEFROG", False) else "순방향"

        import pandas as pd
        df = pd.read_csv(path, encoding="utf-8-sig")
        df.columns = [c.strip() for c in df.columns]
        shutil.copy(path, f"{path}.bak_{time.strftime('%Y%m%d_%H%M%S')}")

        keep, add, dropped = df, [], 0
        for s in lost:
            fl = fills.get(s) or []
            if not fl:
                print(f"     ✗ {s.split('/')[0]}: 거래소에 체결 없음 — 그대로 둠")
                continue
            times = sorted(_ts_str(f.get("timestamp")) for f in fl)
            lo, hi = times[0], times[-1]
            # 거래소가 덮는 구간의 그 종목 행만 제거 → 구간 밖 옛 기록은 보존
            m = (keep["심볼"].astype(str) == s) & \
                (keep["시간"].astype(str) >= lo) & (keep["시간"].astype(str) <= hi)
            dropped += int(m.sum())
            keep = keep[~m]
            add.extend(_row(f, lev, mode) for f in fl)
            print(f"     · {s.split('/')[0]}: CSV {int(m.sum())}행 제거 → 실측 {len(fl)}행 삽입 ({lo[5:]} ~ {hi[5:]})")

        if not add:
            print("     복구할 실측 체결이 없어 중단")
            return

        rows = keep.values.tolist() + add
        rows.sort(key=lambda r: str(r[0]))
        # 체결ID 중복 제거 — 같은 체결이 두 번 들어가면 손익이 이중 계상된다.
        seen, uniq = set(), []
        for r in rows:
            tid = str(r[11]).strip()
            if tid and tid.lower() != "nan":
                if tid in seen:
                    continue
                seen.add(tid)
            uniq.append(r)
        if len(uniq) != len(rows):
            print(f"     · 체결ID 중복 {len(rows) - len(uniq)}행 제거")
        rows = uniq
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLS)
            w.writerows(rows)

        raw2, paired2 = _pairs(bot)
        after = Counter(p.get("status") for p in paired2)
        still = _lost_symbols(paired2)
        print(f"     → 체결 {len(raw2)} · 짝맞춤 {len(paired2)} · {dict(after)}")
        print(f"     → 진입유실 {'해소' if not still else '잔존: ' + ', '.join(still)}")
    finally:
        os.chdir(cwd)
        sys.path[:] = saved


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rebuild(args[0], apply="--apply" in sys.argv)
