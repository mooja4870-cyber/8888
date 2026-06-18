#!/usr/bin/env python3
"""
8888 — 자동매매봇 통합 관제 대시보드
10개 봇(8401~8409, 8501)의 data/ 파일 + 거래소 조회 전용 API를 집계해 한 화면에 표시.
- 봇 폴더는 읽기 전용 (.env의 키도 읽기만, 파일 수정 없음)
- 거래소 호출은 fetch_balance / fetch_positions 조회 전용. 주문 함수 없음.
실행: python3 app.py  →  http://localhost:8888
"""
import csv
import io
import json
import os
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "/Users/l/project"
PORT = 8888
STALE_MIN = 60          # stats.json 갱신이 이보다 오래되면 '지연' 상태
FEED_LIMIT = 15         # 통합 체결 피드 최대 건수
TAIL_BYTES = 16384      # 체결 피드용 trade_history.csv 끝에서 읽을 바이트
WL_TAIL_BYTES = 131072  # 당일 승률 계산용 (당일 청산을 모두 포함하도록 넉넉히)
EX_REFRESH_SEC = 15     # 거래소 잔고/포지션 캐시 갱신 주기
SEED_OVERRIDE = None    # 전체 누적수익률 기준금(seed 합계). None=활성봇 seed 자동합산. (6봇 체제 전환으로 10봇 기준 151 해제 — 고정 원하면 숫자 지정)

BOTS = [
    ("8401_okx", 8401, "OKX"), ("8402_okx", 8402, "OKX"), ("8403_okx", 8403, "OKX"),
    ("8404_okx", 8404, "OKX"), ("8405_okx", 8405, "OKX"), ("8406_okx", 8406, "OKX"),
    ("8407_bnc", 8407, "BNC"), ("8408_bnc", 8408, "BNC"), ("8409_bnc", 8409, "BNC"),
    ("8501_bnc", 8501, "BNC"),
]
# 봇 그룹: 메인(관제 주력 6봇) / 서브(분리 4봇). 화면 드롭다운으로 전환.
HIDDEN_BOTS = {"8402_okx", "8403_okx", "8407_bnc", "8501_bnc"}   # = 서브
ACTIVE_BOTS = [b for b in BOTS if b[0] not in HIDDEN_BOTS]       # = 메인 6봇
SUB_BOTS = [b for b in BOTS if b[0] in HIDDEN_BOTS]              # 서브 4봇


def group_bots(group):
    return SUB_BOTS if group == "sub" else ACTIVE_BOTS


def port_alive(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def read_csv_tail(path, tail_bytes):
    """CSV 끝부분만 읽어 행 리스트 반환 (헤더/잘린 줄 제거)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - tail_bytes))
            chunk = f.read().decode("utf-8-sig", errors="replace")
        lines = [ln for ln in chunk.splitlines() if ln.strip()]
        if size > tail_bytes and lines:
            lines = lines[1:]
        rows = list(csv.reader(io.StringIO("\n".join(lines))))
        return [r for r in rows if len(r) >= 8 and not r[0].startswith("﻿시간") and r[0] != "시간"]
    except OSError:
        return []


def _pnl(row):
    try:
        return float(row[6])
    except (ValueError, IndexError):
        return 0.0


def tail_trades(path, n=5):
    return [{"time": r[0], "symbol": r[1].split("/")[0], "type": r[2],
             "side": r[3], "pnl": round(_pnl(r), 4)}
            for r in read_csv_tail(path, TAIL_BYTES)[-n:]]


_HIST_CACHE = {}   # path -> (mtime, size, exits[])  ;  exits = [(ts19, pnl, oid), ...]
_ENTRY_CACHE = {}  # path -> (mtime, size, entries[])  ;  entries = [(ts19, oid), ...]


def _load_entries(path):
    """trade_history.csv의 진입 행 전체를 (시각, 주문ID)로 파싱. mtime 캐시."""
    try:
        mt = os.path.getmtime(path)
        sz = os.path.getsize(path)
    except OSError:
        return []
    c = _ENTRY_CACHE.get(path)
    if c and c[0] == mt and c[1] == sz:
        return c[2]
    entries = []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.reader(f):
                if len(r) < 3 or r[2] != "진입":
                    continue
                ts = r[0].strip()[:19]
                if not ts[:4].isdigit():
                    continue
                oid = r[10].strip() if len(r) > 10 else ""
                entries.append((ts, oid))
    except OSError:
        return []
    _ENTRY_CACHE[path] = (mt, sz, entries)
    return entries


def _load_exits(path):
    """trade_history.csv의 청산 행 전체를 (시각, 수익, 주문ID)로 파싱. mtime 캐시."""
    try:
        mt = os.path.getmtime(path)
        sz = os.path.getsize(path)
    except OSError:
        return []
    c = _HIST_CACHE.get(path)
    if c and c[0] == mt and c[1] == sz:
        return c[2]
    exits = []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.reader(f):
                if len(r) < 7 or r[2] != "청산":
                    continue
                ts = r[0].strip()[:19]
                if not ts[:4].isdigit():
                    continue
                oid = r[10].strip() if len(r) > 10 else ""
                exits.append((ts, _pnl(r), oid))
    except OSError:
        return []
    _HIST_CACHE[path] = (mt, sz, exits)
    return exits


_EVT_CACHE = {}


def last_entry_exit(path, perf_start=None):
    """trade_history.csv에서 마지막 진입 시각·마지막 청산 시각 반환(문자열, mtime 캐시).
    무진입/무포지션은 '초기화(perf_start) 이후' 기준이어야 하므로 perf_start 이전 이벤트는 제외.
    (초기화 직전 잔존 청산/진입이 stale하게 잡혀 봇 간 표기 불일치 유발하던 버그 교정)"""
    try:
        mt = os.path.getmtime(path)
        sz = os.path.getsize(path)
    except OSError:
        return (None, None)
    ps = (perf_start or "")[:19]
    ck = (mt, sz, ps)
    c = _EVT_CACHE.get(path)
    if c and c[0] == ck:
        return c[1]
    le = lx = None
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.reader(f):
                if len(r) < 3:
                    continue
                ts = r[0].strip()[:19]
                if not ts[:4].isdigit():
                    continue
                if ps and ts < ps:          # 초기화 이전 이벤트 제외
                    continue
                t = r[2].strip()
                if t == "진입" and (le is None or ts > le):
                    le = ts
                elif t == "청산" and (lx is None or ts > lx):
                    lx = ts
    except OSError:
        return (None, None)
    res = (le, lx)
    _EVT_CACHE[path] = (ck, res)
    return res


def hist_metrics(path, perf_start):
    """봇 대시보드와 동일하게 trade_history.csv에서 당일/누적 지표 재계산.
    - 금일 실현 손익 = Σ(청산 수익), 경계 = max(오늘 00:00 KST, perf_start). 행 단위 합산.
    - 당일/누적 주문·승률 = order_id별로 묶어 합산 > 0 승 / < 0 패 (봇 방식).
    - 24시간 내 진입 수 = 현재 시각 기준 직전 24시간 롤링 윈도우 내 진입 기록 수 (청산 무관).
    """
    today0 = time.strftime("%Y-%m-%d 00:00:00")
    ps = (perf_start or "")[:19]
    b_today = max(today0, ps) if ps else today0
    b_since = ps or today0
    exits = _load_exits(path)
    entries = _load_entries(path)

    today_pnl = 0.0
    today_grp, since_grp = {}, {}
    for ts, pnl, oid in exits:
        if ts >= b_since:
            if oid:
                since_grp[oid] = since_grp.get(oid, 0.0) + pnl
            if ts >= b_today:
                today_pnl += pnl
                if oid:
                    today_grp[oid] = today_grp.get(oid, 0.0) + pnl

    tw = sum(1 for v in today_grp.values() if v > 0)
    tl = sum(1 for v in today_grp.values() if v < 0)
    sw = sum(1 for v in since_grp.values() if v > 0)
    sl = sum(1 for v in since_grp.values() if v < 0)

    # 봇 효율 지표 (누적 perf_start 이후, order_id 그룹 손익 기준) ── TradeZella 8대 KPI 일부
    #   profit_factor = 총이익 ÷ 총손실(절대값)  [1.5+ 우수]
    #   avg_wl        = 평균이익 ÷ 평균손실       [1.5x+ 안정]
    #   expectancy    = 누적 실현손익 ÷ 거래수    [양수면 엣지]
    wins = [v for v in since_grp.values() if v > 0]
    losses = [abs(v) for v in since_grp.values() if v < 0]
    gross_win, gross_loss = sum(wins), sum(losses)
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None
    avg_wl = None
    if wins and losses:
        avg_wl = round((gross_win / len(wins)) / (gross_loss / len(losses)), 2)
    n_grp = len(since_grp)
    expectancy = round(sum(since_grp.values()) / n_grp, 4) if n_grp else None

    # 기간별 진입 수 = 현재 시각 기준 직전 N시간 롤링 윈도우 내 진입 기록 수 (청산 무관)
    now = time.time()
    periods = {"1h": 3600, "6h": 21600, "12h": 43200, "24h": 86400,
               "48h": 172800, "72h": 259200, "1w": 604800}
    entries_by_period = {}
    for key, secs in periods.items():
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - secs))
        entries_by_period[key] = sum(1 for ts, oid in entries if ts >= cutoff)

    return {"today_pnl": round(today_pnl, 4), "today_w": tw, "today_l": tl,
            "since_w": sw, "since_l": sl, "since_orders": sw + sl,
            "profit_factor": profit_factor, "avg_wl": avg_wl, "expectancy": expectancy,
            "entries_24h": entries_by_period["24h"], "entries_by_period": entries_by_period}


def drawdown_metrics(path, perf_start, seed):
    """[2단계] 실현손익 equity curve로 최대낙폭(누적)·당일낙폭 계산 (seed 대비 %).
    - equity = seed + 누적 실현손익. peak 대비 하락폭의 최저값 = 최대 낙폭(MDD).
    - 당일 낙폭 = 오늘 시작 잔고 기준, 오늘 내 고점 대비 현재 하락폭.
    - 미실현(보유 포지션) 미반영 — 실현 청산 기준.
    """
    if not seed or seed <= 0:
        return {"max_dd": None, "today_dd": None}
    ps = (perf_start or "")[:19]
    today0 = time.strftime("%Y-%m-%d 00:00:00")
    exits = sorted(_load_exits(path))   # (ts, pnl, oid) 시각 오름차순

    # 누적 최대 낙폭 (perf_start 이후 전체)
    eq = peak = seed
    max_dd = 0.0
    eq_at_today_start = seed
    for ts, pnl, oid in exits:
        if ps and ts < ps:
            continue
        if ts < today0:
            eq_at_today_start = eq + pnl   # 오늘 시작 직전까지의 누적 잔고
        eq += pnl
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    # 당일 낙폭 (오늘 시작 잔고를 peak 기준으로, 오늘 거래만)
    eqt = peak_t = eq_at_today_start
    today_dd = 0.0
    for ts, pnl, oid in exits:
        if ps and ts < ps:
            continue
        if ts < today0:
            continue
        eqt += pnl
        if eqt > peak_t:
            peak_t = eqt
        dd = (eqt - peak_t) / peak_t * 100
        if dd < today_dd:
            today_dd = dd

    return {"max_dd": round(max_dd, 2), "today_dd": round(today_dd, 2)}


def heatmap_grid(path, perf_start, days=7):
    """[3단계] 최근 N일 청산 실현손익을 요일×시간대(6시간 4구간)로 집계.
    반환: {"wday_bucket": pnl_sum, ...}  (wday 0=월 … 6=일, bucket 0=00–06 … 3=18–24)
    """
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days * 86400))
    grid = {}
    for ts, pnl, oid in _load_exits(path):
        if ts < cutoff:
            continue
        try:
            st = time.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        key = "%d_%d" % (st.tm_wday, st.tm_hour // 6)
        grid[key] = grid.get(key, 0.0) + pnl
    return grid


# ── 거래소 조회 전용 클라이언트 (15초 캐시, 백그라운드 갱신) ──────────────

def parse_env(path):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def read_bot_config(folder):
    """각 봇의 config.json 읽기 → 비교표용 핵심변수 추출"""
    cfg_path = os.path.join(BASE, folder, "config.json")
    # STRATEGY_MODE/TYPE 없는 봇의 매매기법 (실거래 active_positions strategy_type 기반)
    strategy_map = {
        "8404_okx": "Breakout",
        "8406_okx": "BoxRange",
    }
    # 전략 '표시명' 강제 override (mooja 지정) — config/보유포지션 strategy_type보다 최우선.
    # 봇이 전략을 바꿨으나 config/잔존 포지션이 옛 이름을 가리킬 때 대시보드 표기 교정용(봇 소스 무수정).
    strategy_override = {
        "8402_okx": "가격 다이버전스",
        "8403_okx": "Dynamic Vol + Symbol",
        "8407_bnc": "Fabio",
    }
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        # 라이브 봇이 config.json을 런타임에 자가수정 → 실거래 포지션의 strategy_type를
        # 1순위로 본다(가장 안정적·정직). 무포지션이면 config 선언 → 정적 매핑 순으로 폴백.
        live = ""
        try:
            pos = json.load(open(os.path.join(BASE, folder, "data", "active_positions.json"), encoding="utf-8"))
            stset = sorted({v.get("strategy_type") for v in pos.values()
                            if isinstance(v, dict) and v.get("strategy_type")})
            live = "/".join(stset)
        except (OSError, json.JSONDecodeError, ValueError, AttributeError):
            pass
        strategy = (strategy_override.get(folder) or live or cfg.get("STRATEGY_MODE")
                    or cfg.get("STRATEGY_TYPE") or strategy_map.get(folder, "—"))
        return {
            "leverage": cfg.get("LEVERAGE", "—"),
            "margin_usdt": cfg.get("MARGIN_USDT", "—"),
            "max_positions": cfg.get("MAX_POSITIONS", "—"),
            "stop_loss_pct": f"{cfg.get('STOP_LOSS_PCT', 0)*100:.2f}%",
            "take_profit_pct": f"{cfg.get('TAKE_PROFIT_PCT', 0)*100:.2f}%",
            "timeframe": cfg.get("TIMEFRAME", "—"),
            "ema_period": cfg.get("EMA_PERIOD", "—"),
            "rsi_period": cfg.get("RSI_PERIOD", "—"),
            "strategy": strategy,
            "max_holding_hours": cfg.get("MAX_HOLDING_HOURS", "—"),
        }
    except (OSError, json.JSONDecodeError, ValueError):
        return {k: "—" for k in ["leverage", "margin_usdt", "max_positions", "stop_loss_pct",
                                  "take_profit_pct", "timeframe", "ema_period", "rsi_period",
                                  "strategy", "max_holding_hours"]}


def bot_creds(folder, ex):
    e = parse_env(os.path.join(BASE, folder, ".env"))
    if ex == "OKX":
        return ("okx", e.get("OKX_API_KEY", ""), e.get("OKX_SECRET_KEY", ""),
                e.get("OKX_PASSPHRASE", ""))
    # 봇마다 시크릿 키 이름 상이(BINANCE_SECRET_KEY 또는 BINANCE_API_SECRET) → 둘 다 허용
    return ("binanceusdm", e.get("BINANCE_API_KEY", ""),
            e.get("BINANCE_SECRET_KEY") or e.get("BINANCE_API_SECRET", ""), "")


EX_CACHE = {}           # folder -> {balance, free, used, upnl, ok, err}
_ex_clients = {}        # cred key -> ccxt client (재사용)
_ex_lock = threading.Lock()


def fetch_account(cred):
    """조회 전용: 잔고/포지션만 읽는다. 주문 관련 호출 없음."""
    import ccxt
    with _ex_lock:
        c = _ex_clients.get(cred)
        if c is None:
            ex_id, key, sec, pw = cred
            cls = getattr(ccxt, ex_id)
            cfg = {"apiKey": key, "secret": sec, "enableRateLimit": True, "timeout": 10000}
            if pw:
                cfg["password"] = pw
            c = cls(cfg)
            if ex_id == "okx":
                # ccxt 4.5.x: 전체 마켓 로드 시 id=None 마켓 정렬 버그 회피 (swap만 사용)
                c.options["fetchMarkets"] = ["swap"]
            _ex_clients[cred] = c
    bal = c.fetch_balance()
    usdt = bal.get("USDT", {})
    upnl = 0.0
    try:
        for p in c.fetch_positions():
            v = p.get("unrealizedPnl")
            if v is not None and float(p.get("contracts") or 0) != 0:
                upnl += float(v)
    except Exception:
        pass
    return {"balance": usdt.get("total"), "free": usdt.get("free"),
            "used": usdt.get("used"), "upnl": round(upnl, 4), "ok": True, "err": None}


_ex_cooldown = {}       # cred -> 이 시각(epoch)까지 조회 스킵 (레이트리밋 백오프)
_ex_backoff = {}        # cred -> 현재 백오프 초
RL_BACKOFF_START = 300  # 첫 레이트리밋 시 5분 쿨다운
RL_BACKOFF_MAX = 1800   # 최대 30분


def _is_rate_limit(e):
    """바이낸스 418/-1003 'too many requests' 등 레이트리밋·IP차단 판별."""
    m = str(e)
    return ("418" in m or "-1003" in m or "Too many" in m
            or "Way too many" in m or "ratelimit" in m.lower())


def exchange_loop():
    while True:
        creds = {}
        for folder, _port, ex in BOTS:
            creds.setdefault(bot_creds(folder, ex), []).append(folder)
        now = time.time()
        for cred, folders in creds.items():
            if not cred[1]:
                r = {"ok": False, "err": "API 키 없음"}
            elif _ex_cooldown.get(cred, 0) > now:
                continue   # 레이트리밋 쿨다운 중 → 조회 스킵(직전 값 유지, 더 안 두드림)
            else:
                try:
                    r = fetch_account(cred)
                    _ex_backoff[cred] = 0          # 성공 → 백오프 리셋
                    _ex_cooldown.pop(cred, None)
                except Exception as e:
                    msg = str(e)[:120]
                    if _is_rate_limit(e):          # 레이트리밋 → 지수 백오프 쿨다운
                        bo = min(max(_ex_backoff.get(cred, 0) * 2, RL_BACKOFF_START), RL_BACKOFF_MAX)
                        _ex_backoff[cred] = bo
                        _ex_cooldown[cred] = now + bo
                    # 직전 정상 잔고가 있으면 None으로 덮지 않고 '지연(stale)'으로 유지
                    prev = next((EX_CACHE.get(f) for f in folders if EX_CACHE.get(f)), None)
                    if prev and prev.get("balance") is not None:
                        r = {**prev, "ok": True, "stale": True, "err": msg}
                    else:
                        r = {"ok": False, "err": msg}
            for f in folders:
                EX_CACHE[f] = r
        time.sleep(EX_REFRESH_SEC)


# ── 봇별 파일 기반 지표 ──────────────────────────────────────────────

def app_debug_time(folder):
    """봇 폴더의 app.py + core/*.py 중 가장 최근 수정시각(KST 문자열). '앱 최종 디버깅 후 경과' 표시용. 읽기(stat)만 수행."""
    base = os.path.join(BASE, folder)
    paths = [os.path.join(base, "app.py")]
    core = os.path.join(base, "core")
    try:
        paths += [os.path.join(core, f) for f in os.listdir(core) if f.endswith(".py")]
    except OSError:
        pass
    latest = 0.0
    for p in paths:
        try:
            mt = os.path.getmtime(p)
            if mt > latest:
                latest = mt
        except OSError:
            pass
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest)) if latest else None


def bot_status(folder, port, ex):
    d = os.path.join(BASE, folder, "data")
    r = {"name": folder.split("_")[0], "folder": folder, "port": port, "ex": ex,
         "alive": port_alive(port), "daily": None, "total": None, "wins": 0,
         "losses": 0, "seed": None, "perf_start": None, "orders_today": 0,
         "total_trades": 0, "age_min": None, "positions": [], "trades": []}
    sp = os.path.join(d, "stats.json")
    try:
        with open(sp, encoding="utf-8") as f:
            s = json.load(f)
        r["daily"] = s.get("daily_pnl_usdt")
        r["total"] = s.get("total_pnl_usdt")
        r["wins"] = s.get("total_wins") or 0
        r["losses"] = s.get("total_losses") or 0
        r["seed"] = s.get("seed_money")
        r["perf_start"] = s.get("perf_start_time")
        r["orders_today"] = s.get("orders_today") or 0
        r["total_trades"] = s.get("total_trades") or 0
        r["age_min"] = round((time.time() - os.path.getmtime(sp)) / 60, 1)
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(d, "active_positions.json"), encoding="utf-8") as f:
            r["positions"] = [k.split("/")[0] for k in json.load(f)]
    except (OSError, ValueError):
        pass
    hist = os.path.join(d, "trade_history.csv")
    r["trades"] = tail_trades(hist)
    # ⏸무진입 = 마지막 진입 이후 경과, ⏸무포지션 = 마지막 청산 이후(현재 무포지션일 때) 경과
    r["last_entry"], r["last_flat"] = last_entry_exit(hist, r["perf_start"])
    r["config"] = read_bot_config(folder)
    r["app_debug"] = app_debug_time(folder)   # 앱 최종 디버깅(app.py+core/*.py 최신 mtime)
    # 금일 실현 손익·당일/누적 주문·승률을 봇 화면과 동일하게 trade_history에서 재계산
    m = hist_metrics(hist, r["perf_start"])
    r["today_pnl"] = m["today_pnl"]            # 금일 실현 손익 (봇 화면값)
    r["today_w"], r["today_l"] = m["today_w"], m["today_l"]
    r["orders_today"] = m["today_w"] + m["today_l"]
    r["since_w"], r["since_l"] = m["since_w"], m["since_l"]
    r["since_orders"] = m["since_orders"]
    r["entries_24h"] = m["entries_24h"]   # 24시간 내 진입 수 (청산 무관, 롤링 윈도우)
    r["entries_by_period"] = m["entries_by_period"]   # 기간별 진입 수(1h~1w 롤링)
    r["profit_factor"] = m["profit_factor"]   # 봇 효율: 총이익÷총손실 (1.5+ 우수)
    r["avg_wl"] = m["avg_wl"]                  # 봇 효율: 평균이익÷평균손실 (1.5x+ 안정)
    r["expectancy"] = m["expectancy"]         # 봇 효율: 거래당 평균 손익 (양수=엣지)
    dd = drawdown_metrics(hist, r["perf_start"], r["seed"])
    r["max_dd"] = dd["max_dd"]                 # [2단계] 최대 낙폭(누적, %)
    r["today_dd"] = dd["today_dd"]             # [2단계] 당일 낙폭(%)
    r["hm_grid"] = heatmap_grid(hist, r["perf_start"])   # [3단계] 요일×시간대 실현손익(7일)
    r.update({"ex_" + k: v for k, v in EX_CACHE.get(folder, {"ok": False, "err": "조회 전"}).items()})

    # 누적 수익률 = (현재 총잔고 - 초기화 잔고) / 초기화 잔고  ← 봇 대시보드 툴팁과 동일
    #   일시   = perf_start_time(stats.json),  초기화 잔고 = seed_money(stats.json)
    #   현재 총잔고 = 거래소 실시간 잔고. 조회 실패 시 실현손익 기준으로 폴백.
    days = bot_days(r["perf_start"])
    r["days"] = round(days, 2)
    if r["seed"]:
        if r.get("ex_ok") and r.get("ex_balance") is not None:
            r["cum_delta"] = round(r["ex_balance"] - r["seed"], 4)
            r["cum_basis"] = "balance"
        else:
            r["cum_delta"] = round(r["total"] or 0, 4)   # 폴백: 실현손익
            r["cum_basis"] = "pnl"
        r["cum_ret"] = round(r["cum_delta"] / r["seed"] * 100, 2)
        r["daily_ret"] = round(r["cum_ret"] / days, 2)
    else:
        r["cum_ret"] = r["daily_ret"] = r["cum_delta"] = None
        r["cum_basis"] = None
    # 보유 여부 = 거래소 실제 증거금 사용(ex_used>0) 기준. 조회 실패 시에만 active_positions 파일 폴백.
    # (봇이 청산 후 active_positions.json을 안 지워 생기는 '유령 포지션' 오집계 방지 — 예: 8501)
    r["holding"] = ((r.get("ex_used") or 0) > 0) if r.get("ex_ok") else bool(r.get("positions"))
    return r


def bot_days(perf_start):
    try:
        t0 = time.mktime(time.strptime(perf_start, "%Y-%m-%d %H:%M:%S"))
        return max(1.0, (time.time() - t0) / 86400)
    except (TypeError, ValueError):
        return 1.0


def collect(group="main"):
    bots = [bot_status(*b) for b in group_bots(group)]
    # 합산 누적 수익률 = (Σ현재 총잔고 - 기준금) / 기준금
    #   기준금 = SEED_OVERRIDE(mooja 지정 고정값) 우선, 없으면 봇 seed 자동합산.
    #   현재 총잔고는 거래소 실시간 잔고, 조회 실패 봇은 seed+실현손익으로 폴백.
    seed = SEED_OVERRIDE if SEED_OVERRIDE else sum(b["seed"] or 0 for b in bots)
    assets = 0.0
    for b in bots:
        if b.get("ex_ok") and b.get("ex_balance") is not None:
            assets += b["ex_balance"]
        else:
            assets += (b["seed"] or 0) + (b["total"] or 0)
    days = max([bot_days(b["perf_start"]) for b in bots] or [1.0])
    cum_ret = round((assets - seed) / seed * 100, 2) if seed else None

    # [3단계] 전봇 히트맵 합산 (요일×시간대 실현손익, 최근 7일)
    heatmap = {}
    for b in bots:
        for k, v in (b.get("hm_grid") or {}).items():
            heatmap[k] = round(heatmap.get(k, 0.0) + v, 4)
        b.pop("hm_grid", None)   # 합산 완료 → 봇별 grid는 페이로드에서 제거(경량화)
    # [2단계] Drawdown 경고 대상 = 당일 낙폭 -10% 초과(위험) / -5% 초과(주의)
    dd_danger = [{"name": b["name"], "today_dd": b["today_dd"]}
                 for b in bots if b.get("today_dd") is not None and b["today_dd"] <= -10]
    dd_warn = [{"name": b["name"], "today_dd": b["today_dd"]}
               for b in bots if b.get("today_dd") is not None and -10 < b["today_dd"] <= -5]

    summary = {
        "assets": round(assets, 2),
        "cum_ret": cum_ret,
        "cum_delta": round(assets - seed, 2),
        "daily_ret": round(cum_ret / days, 2) if cum_ret is not None else None,
        "days": round(days, 1),
        "alive": sum(1 for b in bots if b["alive"]),
        "count": len(bots),
        "with_positions": sum(1 for b in bots if b["holding"]),
        "no_positions": [b["name"] for b in bots if not b["holding"]],
        "stale": [b["name"] for b in bots
                  if b["age_min"] is not None and b["age_min"] > STALE_MIN],
        "heatmap": heatmap,
        "dd_danger": dd_danger,
        "dd_warn": dd_warn,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    return {"summary": summary, "bots": bots, "stale_min": STALE_MIN}


# ── 시간별 스냅샷 기록 (매시 :00·:30, 봇별 일평균수익률 누적) ──────────────
SNAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots.json")
SNAP_KEEP = 48          # 최근 48행(=30분×48=24시간) 보관
SNAP_LOCK = threading.Lock()


def load_snapshots():
    try:
        with open(SNAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def record_snapshot():
    """현재 봇별 일평균수익률을 1행 스냅샷으로 누적(최근 SNAP_KEEP행 유지). total_assets 포함.
    거래소 캐시 콜드(다수 봇 ex_ok=False) 시엔 총자산이 폴백값으로 왜곡되므로 기록 스킵."""
    data = collect()
    ex_ok = sum(1 for b in data["bots"] if b.get("ex_ok"))
    if ex_ok < len(data["bots"]) * 0.7:    # 70% 미만 = 콜드 → 오염 방지 위해 기록 안 함
        return None
    ts = time.strftime("%Y-%m-%d %H:%M")
    row = {"ts": ts, "t": time.strftime("%H:%M"),
           "total_assets": data["summary"]["assets"],
           "bots": {b["name"]: b.get("daily_ret") for b in data["bots"]}}
    with SNAP_LOCK:
        snaps = load_snapshots()
        if snaps and snaps[-1].get("ts") == ts:      # 같은 분 중복 → 대체
            snaps[-1] = row
        else:
            snaps.append(row)
        snaps = snaps[-SNAP_KEEP:]
        tmp = SNAP_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snaps, f, ensure_ascii=False)
        os.replace(tmp, SNAP_PATH)
    return row


def snapshot_loop():
    # 재시작 직후 즉시 기록은 거래소 콜드값으로 오염 + off-grid 행 생성 → 제거.
    # 다음 :00/:30 경계에만 기록(콜드면 record_snapshot 내부에서 스킵).
    while True:
        lt = time.localtime()
        sec_into = lt.tm_min * 60 + lt.tm_sec
        wait = 1800 - (sec_into % 1800)   # 다음 :00/:30 경계까지(초)
        time.sleep(wait if wait > 0 else 1800)
        try:
            record_snapshot()
        except Exception:
            pass


# ── [B안] 총자산 고빈도 기록(1분) + BTC 가격 차트 데이터 ──────────────────────
ASSET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "asset_history.json")
ASSET_KEEP = 10080      # 1분 간격 × 10080 = 7일 보관
ASSET_LOCK = threading.Lock()


def load_asset_history():
    try:
        with open(ASSET_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _seed_asset_history():
    """asset_history가 비었으면 기존 30분 스냅샷(total_assets)으로 백필 → 즉시 막대 표시."""
    if load_asset_history():
        return
    seed = []
    for r in load_snapshots():
        if r.get("total_assets") is None:
            continue
        ts = r.get("ts", "")
        if len(ts) == 16:          # "YYYY-MM-DD HH:MM" → 초 보강
            ts += ":00"
        seed.append({"ts": ts, "v": r["total_assets"]})
    if seed:
        with ASSET_LOCK:
            tmp = ASSET_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(seed[-ASSET_KEEP:], f, ensure_ascii=False)
            os.replace(tmp, ASSET_PATH)


def record_asset():
    """현재 총자산(Σ잔고)을 1분 1행으로 누적(최근 ASSET_KEEP행 유지).
    거래소 캐시 콜드 시엔 폴백값 왜곡 방지 위해 기록 스킵."""
    data = collect()
    if sum(1 for b in data["bots"] if b.get("ex_ok")) < len(data["bots"]) * 0.7:
        return
    assets = data["summary"]["assets"]
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with ASSET_LOCK:
        hist = load_asset_history()
        hist.append({"ts": ts, "v": assets})
        hist = hist[-ASSET_KEEP:]
        tmp = ASSET_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False)
        os.replace(tmp, ASSET_PATH)


def asset_loop():
    try:
        _seed_asset_history()
    except Exception:
        pass
    time.sleep(30)        # 거래소 캐시(EX_CACHE) 워밍업 대기 → 기동 폴백값(과소 기록) 방지
    while True:
        try:
            record_asset()
        except Exception:
            pass
        time.sleep(60)


# ── 디스코드 1분 알림: 활성봇 일평균수익률(내림차순) + 직전분 대비 증감(↑🔴/↓🔵) ──────
DISCORD_WH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "discord_webhook.txt")
_discord_prev = {}      # name -> 직전 daily_ret


def _ascii_dash_chart(vals, rows=6):
    """값 리스트를 '-' 문자 미니 라인차트(rows줄)로. 좌측 상/하단에 최고·최저 라벨."""
    if len(vals) < 2:
        return None
    lo = min(vals)
    hi = max(vals)
    rng = hi - lo
    grid = [[" "] * len(vals) for _ in range(rows)]
    for c, v in enumerate(vals):
        r = int(round((v - lo) / rng * (rows - 1))) if rng > 0 else rows // 2
        grid[rows - 1 - r][c] = "-"      # 상단=최고
    out = []
    for i, row in enumerate(grid):
        lab = ("%+.2f" % hi) if i == 0 else (("%+.2f" % lo) if i == rows - 1 else "")
        out.append("%6s|%s" % (lab, "".join(row)))
    return "\n".join(out)


def send_discord_report():
    try:
        wh = open(DISCORD_WH_PATH, encoding="utf-8").read().strip()
    except OSError:
        return
    if not wh:
        return
    data = collect()
    s = data["summary"]
    # 맨 위: 전체(통합) 일평균수익률 + 직전분 대비 증감
    tot = s.get("daily_ret")
    if tot is not None:
        tts = ("+" if tot >= 0 else "") + ("%.2f%%/일" % tot)
        tprev = _discord_prev.get("__ALL__")
        if tprev is None:
            tchg = "(—)"
        else:
            td = round(tot - tprev, 2)
            tchg = ("🔴%.2f%%↑" % abs(td)) if td > 0 else (("🔵%.2f%%↓" % abs(td)) if td < 0 else "⚪0.00%")
        _discord_prev["__ALL__"] = tot
        lines = ["📊 전체 일평균수익률 (%s일)" % s.get("days"),
                 "%s  %s" % (tts, tchg), "────────────────"]
    else:
        lines = ["📊 전체 일평균수익률", "────────────────"]
    bots = sorted(data["bots"],
                  key=lambda b: (b.get("daily_ret") if b.get("daily_ret") is not None else -9e9),
                  reverse=True)   # 일평균수익률 내림차순
    # 봇줄(ANSI 코드블록): 보유=O(노랑 1;33) / 미보유=X(밝은회색 1;30)
    YEL = "\x1b[1;33m"
    GRY = "\x1b[1;30m"
    RST = "\x1b[0m"
    blines = []
    for b in bots:
        n = b["name"]
        mark = (YEL + "O" + RST) if b.get("holding") else (GRY + "X" + RST)
        dr = b.get("daily_ret")
        if dr is None:
            blines.append("%s %s  —" % (mark, n))
            continue
        drs = ("+" if dr >= 0 else "") + ("%.2f%%" % dr)
        prev = _discord_prev.get(n)
        if prev is None:
            chg = "(—)"
        else:
            dlt = round(dr - prev, 2)
            if dlt > 0:
                chg = "🔴%.2f%%↑" % abs(dlt)      # 상승=빨강
            elif dlt < 0:
                chg = "🔵%.2f%%↓" % abs(dlt)      # 하락=파랑
            else:
                chg = "⚪0.00%"
        blines.append("%s %s  %s  %s" % (mark, n, drs, chg))
        _discord_prev[n] = dr
    # 맨 아래: 전체 일평균수익률 최근 30분 '-' 그래프 (asset_history 1분치 → 일평균% 환산)
    chart = None
    npts = 0
    try:
        seedv = (s.get("assets") or 0) - (s.get("cum_delta") or 0)
        days = s.get("days") or 1
        vals = []
        for h in load_asset_history()[-30:]:
            v = h.get("v")
            if v is not None and seedv:
                vals.append((v - seedv) / seedv / days * 100)
        npts = len(vals)
        chart = _ascii_dash_chart(vals)
    except Exception:
        chart = None
    foot = "\n-# " + time.strftime("%Y-%m-%d %H:%M:%S")
    ansi_body = "\n".join(blines)
    if chart:
        ansi_body += ("\n\n최근 %d분 전체 일평균 추이(%%)\n" % npts) + chart
    content = "```ansi\n" + "\n".join(lines) + "\n" + ansi_body + "\n```" + foot
    payload = json.dumps({"content": content}).encode()
    req = urllib.request.Request(wh, data=payload,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0 (8888-bot-monitor)"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def discord_loop():
    time.sleep(25)        # 거래소 워밍업 대기
    while True:
        try:
            send_discord_report()
        except Exception:
            pass
        time.sleep(60)


# ── /loop 노하우 적용 감시 모듈 (탐지·경보만, 재기동/주문은 안전선) ─────────────
LOOP_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loop_state.md")


def _discord_send(text):
    """단문 경보 발송(웹훅 재사용)."""
    try:
        wh = open(DISCORD_WH_PATH, encoding="utf-8").read().strip()
    except OSError:
        return
    if not wh:
        return
    req = urllib.request.Request(wh, data=json.dumps({"content": text}).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0 (8888-bot-monitor)"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def _log_loop_state(line):
    try:
        with open(LOOP_STATE_PATH, "a", encoding="utf-8") as f:
            f.write("- %s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except OSError:
        pass


# [방안1] 엔진 좀비·생존 감시: 포트 다운/데이터 지연이 2회 연속(약3분) 지속 시 경보, 복구 시 해제
_health_prev = {}        # name -> 직전 ok 여부
_health_badcnt = {}      # name -> 연속 이상 횟수


def health_check_once():
    for folder, port, ex in BOTS:
        name = folder.split("_")[0]
        up = port_alive(port)
        sp = os.path.join(BASE, folder, "data", "stats.json")
        try:
            age = (time.time() - os.path.getmtime(sp)) / 60.0
        except OSError:
            age = None
        stale = (age is not None and age > STALE_MIN)
        ok = up and not stale
        bad = _health_badcnt.get(name, 0)
        bad = 0 if ok else bad + 1
        _health_badcnt[name] = bad
        sustained_bad = bad >= 2          # 2회 연속(≈3분) 지속
        prev = _health_prev.get(name)     # 직전 '경보 상태'(True=정상, False=경보중)
        if prev is None:
            _health_prev[name] = not sustained_bad
            continue
        if prev and sustained_bad:        # 정상→이상
            reason = "포트 다운" if not up else ("데이터 지연 %.0f분" % (age or 0))
            _discord_send("🔴 [생존경보] 봇 %s 이상 — %s (엔진 좀비/다운 의심)" % (name, reason))
            _log_loop_state("[방안1] %s 이상 (%s)" % (name, reason))
            _health_prev[name] = False
        elif (not prev) and ok:           # 이상→복구
            _discord_send("🟢 [복구] 봇 %s 정상화" % name)
            _log_loop_state("[방안1] %s 복구" % name)
            _health_prev[name] = True


def health_loop():
    time.sleep(40)        # 기동 워밍업
    while True:
        try:
            health_check_once()
        except Exception:
            pass
        time.sleep(90)


# [방안2] 청산/주문 오류 실시간 스캔: 봇 로그 신규줄에서 치명 패턴 탐지 → 디스코드 경보(봇당 15분 스로틀)
_errscan_pos = {}        # logpath -> 마지막 읽은 바이트
_err_alert_ts = {}       # name -> 마지막 경보 epoch
ERR_PATTERNS = ("청산 감지 오류", "진입유실", "보호주문 실패", "주문 실패",
                "주문 거부", "주문 거절", "Traceback", "has no attribute")


def _scan_log_new(path):
    try:
        sz = os.path.getsize(path)
    except OSError:
        return []
    pos = _errscan_pos.get(path)
    if pos is None:                  # 최초: 백로그 무시(현재 끝부터)
        _errscan_pos[path] = sz
        return []
    if sz < pos:                     # 로테이션/트렁케이트
        pos = 0
    if sz == pos:
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            f.seek(pos)
            chunk = f.read()
    except OSError:
        return []
    _errscan_pos[path] = sz
    hits = []
    for ln in chunk.splitlines():
        if any(p in ln for p in ERR_PATTERNS):
            hits.append(ln.strip()[:160])
    return hits


def errscan_check_once():
    now = time.time()
    for folder, port, ex in BOTS:
        name = folder.split("_")[0]
        hits = []
        for fn in ("headless_runner.log", "streamlit_server.log", "bot_engine.log"):
            hits += _scan_log_new(os.path.join(BASE, folder, fn))
        if not hits:
            continue
        if now - _err_alert_ts.get(name, 0) < 900:   # 15분 스로틀
            _log_loop_state("[방안2] %s 오류 %d건(스로틀)" % (name, len(hits)))
            continue
        _err_alert_ts[name] = now
        samp = hits[-1].replace("```", "ˋˋˋ")
        _discord_send("🟠 [청산/주문오류] 봇 %s — 신규 %d건\n```\n%s\n```" % (name, len(hits), samp))
        _log_loop_state("[방안2] %s 오류 %d건: %s" % (name, len(hits), samp))


def errscan_loop():
    time.sleep(50)
    while True:
        try:
            errscan_check_once()
        except Exception:
            pass
        time.sleep(120)


# [방안3] 보유 포지션 무방비 감시: 보유중(EX_CACHE used>0)인데 엔진 다운/지연이면
#         트레일링·동적청산이 멈춰 손절 관리가 중단됨 → 긴급 경보 (추가 거래소 호출 없음)
_protect_prev = {}       # name -> 직전 무방비 여부


def protect_check_once():
    for folder, port, ex in BOTS:
        name = folder.split("_")[0]
        exd = EX_CACHE.get(folder, {})
        holding = ((exd.get("used") or 0) > 0) if exd.get("ok") else False
        up = port_alive(port)
        sp = os.path.join(BASE, folder, "data", "stats.json")
        try:
            age = (time.time() - os.path.getmtime(sp)) / 60.0
        except OSError:
            age = None
        stale = (age is not None and age > STALE_MIN)
        unguarded = holding and (not up or stale)
        prev = _protect_prev.get(name, False)
        if unguarded and not prev:
            why = "엔진 포트 다운" if not up else ("데이터 지연 %.0f분" % (age or 0))
            _discord_send("🔴 [무방비포지션] 봇 %s 보유중인데 %s — 트레일링/동적청산 중단(거래소 고정SL만 의존). 점검 요망!" % (name, why))
            _log_loop_state("[방안3] %s 무방비 (%s)" % (name, why))
            _protect_prev[name] = True
        elif (not unguarded) and prev:
            _discord_send("🟢 [해제] 봇 %s 포지션 관리 정상화" % name)
            _log_loop_state("[방안3] %s 해제" % name)
            _protect_prev[name] = False


def protect_loop():
    time.sleep(60)
    while True:
        try:
            protect_check_once()
        except Exception:
            pass
        time.sleep(90)


# [방안4] 드로우다운 서킷 감시: 봇별 당일 낙폭 -5%(주의)/-10%(위험) 단계 상승 시 경보
_dd_prev = {}            # name -> 직전 단계('ok'/'warn'/'danger')
_DD_RANK = {"ok": 0, "warn": 1, "danger": 2}


def dd_check_once():
    for folder, port, ex in BOTS:
        name = folder.split("_")[0]
        sp = os.path.join(BASE, folder, "data", "stats.json")
        try:
            with open(sp, encoding="utf-8") as f:
                st = json.load(f)
            seed = st.get("seed_money")
            ps = st.get("perf_start_time")
        except (OSError, ValueError):
            continue
        hist = os.path.join(BASE, folder, "data", "trade_history.csv")
        dd = drawdown_metrics(hist, ps, seed).get("today_dd")
        if dd is None:
            continue
        level = "danger" if dd <= -10 else ("warn" if dd <= -5 else "ok")
        prev = _dd_prev.get(name, "ok")
        if _DD_RANK[level] > _DD_RANK[prev]:        # 단계 악화
            icon = "🔴 위험" if level == "danger" else "🟠 주의"
            _discord_send("%s [낙폭] 봇 %s 당일 낙폭 %.1f%% (한계 %s)" % (icon, name, dd, "-10%" if level == "danger" else "-5%"))
            _log_loop_state("[방안4] %s 낙폭 %.1f%% (%s)" % (name, dd, level))
        elif level == "ok" and prev != "ok":        # 회복
            _discord_send("🟢 [낙폭해소] 봇 %s 당일 낙폭 정상권" % name)
            _log_loop_state("[방안4] %s 낙폭 해소" % name)
        _dd_prev[name] = level


def dd_loop():
    time.sleep(70)
    while True:
        try:
            dd_check_once()
        except Exception:
            pass
        time.sleep(300)        # 5분


# [방안5] 일 1% 진척 + 기회손실 리포트: 매시간 전체/봇별 목표진척·정체(무진입)·미달 다이제스트
def _hours_since(ts):
    try:
        t0 = time.mktime(time.strptime((ts or "")[:19], "%Y-%m-%d %H:%M:%S"))
        return (time.time() - t0) / 3600.0
    except (TypeError, ValueError):
        return None


def report_check_once():
    out = []
    allbots = []
    for grp in ("main", "sub"):
        d = collect(grp)
        s = d["summary"]
        tot = s.get("daily_ret")
        lab = "메인6" if grp == "main" else "서브4"
        out.append("[%s] 전체 일평균 %s/일 (목표 1.00%%) %s" % (
            lab, ("%+.2f%%" % tot) if tot is not None else "—",
            "✅달성" if (tot or 0) >= 1.0 else "미달"))
        allbots += d["bots"]
    lines = ["📈 [일 1%% 진척 리포트] %s시" % time.strftime("%H:%M")]
    lines += out + ["─────"]
    for b in sorted(allbots, key=lambda b: (b.get("daily_ret") if b.get("daily_ret") is not None else -9e9), reverse=True):
        n = b["name"]
        dr = b.get("daily_ret")
        drs = ("%+.2f%%" % dr) if dr is not None else "—"
        icon = "✅" if (dr or 0) >= 1.0 else ("🟡" if (dr or 0) >= 0 else "🔵")
        ne = ""
        if not b.get("holding"):
            h = _hours_since(b.get("last_entry")) or _hours_since(b.get("perf_start"))
            if h is not None and h >= 3:
                ne = " ⏸무진입%.0fh(기회손실?)" % h
        lines.append("%s %s %s%s" % (icon, n, drs, ne))
    _discord_send("\n".join(lines))
    _log_loop_state("[방안5] 진척리포트 발송")


def report_loop():
    time.sleep(120)
    while True:
        try:
            report_check_once()
        except Exception:
            pass
        time.sleep(3600)       # 1시간


_btc_cache = {}         # tf -> (epoch_fetched, candles[[ts_ms, close], ...])
_btc_lock = threading.Lock()
_btc_client = None
BTC_TF_MS = {"1m": 60000, "5m": 300000, "15m": 900000,
             "1h": 3600000, "1d": 86400000, "1M": 2592000000}


def fetch_btc_ohlcv(tf, limit=60):
    """공개 OHLCV(API 키 불필요)로 BTC/USDT 종가 캔들. tf별 30초 캐시."""
    if tf not in BTC_TF_MS:
        tf = "1h"
    now = time.time()
    with _btc_lock:
        c = _btc_cache.get(tf)
        if c and now - c[0] < 30:
            return c[1]
    import ccxt
    global _btc_client
    candles = []
    try:
        with _btc_lock:
            if _btc_client is None:
                _btc_client = ccxt.binance({"enableRateLimit": True, "timeout": 10000})
        raw = _btc_client.fetch_ohlcv("BTC/USDT", timeframe=tf, limit=limit)
        candles = [[r[0], r[4]] for r in raw]   # [ts_ms, 종가]
    except Exception:
        candles = []
    if candles:                                 # 성공 시에만 캐시(실패는 다음 요청서 재시도)
        with _btc_lock:
            _btc_cache[tf] = (now, candles)
    return candles


def asset_chart(tf):
    """BTC 종가(선) + 총자산(막대)을 동일 시간축에 정렬해 반환."""
    import bisect
    tf = tf if tf in BTC_TF_MS else "1h"
    candles = fetch_btc_ohlcv(tf, 60)
    hist = load_asset_history()
    apts = []
    for h in hist:
        try:
            ems = int(time.mktime(time.strptime(h["ts"], "%Y-%m-%d %H:%M:%S")) * 1000)
        except (ValueError, OverflowError):
            continue
        apts.append((ems, h.get("v")))
    apts.sort()
    keys = [p[0] for p in apts]
    interval = BTC_TF_MS[tf]
    points = []
    for ts_ms, close in candles:
        cutoff = ts_ms + interval               # 캔들 종료시점 이하의 마지막 자산값(전방채움)
        idx = bisect.bisect_right(keys, cutoff) - 1
        asset = apts[idx][1] if idx >= 0 else None
        points.append({"t": ts_ms, "btc": close, "asset": asset})
    return {"tf": tf, "points": points, "asset_from": hist[0]["ts"] if hist else None}


# dashboard.html은 요청마다 새로 읽는다(파일 수정 시 서버 재시작 없이 반영)
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/status"):
            from urllib.parse import urlparse, parse_qs
            grp = (parse_qs(urlparse(self.path).query).get("group") or ["main"])[0]
            body = json.dumps(collect(grp), ensure_ascii=False).encode()
            ctype = "application/json; charset=utf-8"
        elif self.path.startswith("/api/snapshots"):
            body = json.dumps(load_snapshots(), ensure_ascii=False).encode()
            ctype = "application/json; charset=utf-8"
        elif self.path.startswith("/api/assetchart"):
            from urllib.parse import urlparse, parse_qs
            tf = (parse_qs(urlparse(self.path).query).get("tf") or ["1h"])[0]
            body = json.dumps(asset_chart(tf), ensure_ascii=False).encode()
            ctype = "application/json; charset=utf-8"
        elif self.path == "/" or self.path.startswith("/index"):
            with open(HTML_PATH, encoding="utf-8") as f:
                body = f.read().encode()
            ctype = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=exchange_loop, daemon=True).start()
    threading.Thread(target=snapshot_loop, daemon=True).start()
    threading.Thread(target=asset_loop, daemon=True).start()   # [B안] 총자산 1분 기록
    threading.Thread(target=discord_loop, daemon=True).start()  # 디스코드 1분 알림
    threading.Thread(target=health_loop, daemon=True).start()   # [방안1] 엔진 생존 감시
    threading.Thread(target=errscan_loop, daemon=True).start()  # [방안2] 청산/주문 오류 스캔
    threading.Thread(target=protect_loop, daemon=True).start()  # [방안3] 보유 포지션 무방비 감시
    threading.Thread(target=dd_loop, daemon=True).start()       # [방안4] 드로우다운 서킷 감시
    threading.Thread(target=report_loop, daemon=True).start()   # [방안5] 일 1% 진척 리포트
    print(f"8888 통합 관제 대시보드: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
