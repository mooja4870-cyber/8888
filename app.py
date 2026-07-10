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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8888
STALE_MIN = 60          # stats.json 갱신이 이보다 오래되면 '지연' 상태
FEED_LIMIT = 15         # 통합 체결 피드 최대 건수
TAIL_BYTES = 16384      # 체결 피드용 trade_history.csv 끝에서 읽을 바이트
WL_TAIL_BYTES = 131072  # 당일 승률 계산용 (당일 청산을 모두 포함하도록 넉넉히)
EX_REFRESH_SEC = 15     # 거래소(OKX) 잔고/포지션 캐시 갱신 주기
BNC_REFRESH_SEC = 300   # 바이낸스(BNC)만 별도 장주기 — IP 레이트리밋/ban 회피(같은 IP 과다조회 방지)
SEED_OVERRIDE = None     # 전체 기준금(초기자본금 합). None=각 봇 stats.json seed_money 실시간 합산.
                         # 봇 재초기화 시 seed_money가 갱신되므로 고정값이 아니라 자동합산해야
                         # 봇별 누적수익률과 전체 누적수익률이 항상 정합(전체 cum_delta = Σ봇별 cum_delta).

BOTS = [
    # 봇 폴더명이 840X_okx → 840X 로 변경됨(mooja 2026-06-29). 폴더·키·기준금 참조명 통일.
    ("8401", 8401, "OKX"),
    ("8402", 8402, "OKX"),
    ("8404", 8404, "OKX"),
    ("8407", 8407, "BNC"),
    ("8408", 8408, "BNC"),
    ("8409", 8409, "BNC"),
]


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
    periods = {"1h": 3600, "4h": 14400, "6h": 21600, "12h": 43200, "24h": 86400,
               "48h": 172800, "72h": 259200, "1w": 604800}
    entries_by_period = {}
    for key, secs in periods.items():
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - secs))
        entries_by_period[key] = sum(1 for ts, oid in entries if ts >= cutoff)

    return {"today_pnl": round(today_pnl, 4), "today_w": tw, "today_l": tl,
            "since_w": sw, "since_l": sl, "since_orders": sw + sl,
            "since_pnl": round(sum(since_grp.values()), 4),   # 초기화(perf_start) 이후 실현손익 = 봇 앱 누적손익
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
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        # 전략명: 하드코딩 override 전면 제거(mooja 지시 2026-06-25) → config STRATEGY_MODE 실시간 우선.
        # 'None'·빈값이면 STRATEGY_TYPE → 실거래 active_positions strategy_type → '—' 순 폴백.
        mode = cfg.get("STRATEGY_MODE")
        if mode in (None, "", "None", "none"):
            mode = None
        live = ""
        try:
            pos = json.load(open(os.path.join(BASE, folder, "data", "active_positions.json"), encoding="utf-8"))
            stset = sorted({v.get("strategy_type") for v in pos.values()
                            if isinstance(v, dict) and v.get("strategy_type")})
            live = "/".join(stset)
        except (OSError, json.JSONDecodeError, ValueError, AttributeError):
            pass
        strategy = mode or cfg.get("STRATEGY_TYPE") or live or "—"
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


def parse_api_md_okx(folder):
    """봇의 api.md에서 활성(주석 제외) OKX 키 파싱.
    봇 본체(core/api_keys.py)와 동일 규칙: #/빈 줄 무시, apikey/secretkey/passphrase만 인식,
    같은 키는 첫 등장값 우선. 세 값 모두 있으면 (key, sec, pw) 반환, 아니면 None."""
    path = os.path.join(BASE, folder, "api.md")
    slot_of = {
        "apikey": "key", "okxapikey": "key",
        "secretkey": "sec", "okxsecretkey": "sec",
        "passphrase": "pw", "okxpassphrase": "pw"
    }
    found = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                rk, _, rv = s.partition("=")
                slot = slot_of.get(rk.strip().lower().replace(" ", "").replace("_", ""))
                if slot and slot not in found:
                    v = rv.strip().strip('"').strip("'").strip()
                    if v:
                        found[slot] = v
    except OSError:
        return None
    if all(k in found for k in ("key", "sec", "pw")):
        return (found["key"], found["sec"], found["pw"])
    return None


def parse_api_md_bnc(folder):
    """봇의 api.md에서 BNC(바이낸스) 키 파싱. 형식: api = ... / secret = ...
    #/빈 줄 무시, 첫 등장값 우선. 두 값 모두 있으면 (key, sec) 반환, 아니면 None."""
    path = os.path.join(BASE, folder, "api.md")
    slot_of = {
        "api": "key", "apikey": "key", "binanceapikey": "key",
        "secret": "sec", "secretkey": "sec", "binancesecretkey": "sec"
    }
    found = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                rk, _, rv = s.partition("=")
                slot = slot_of.get(rk.strip().lower().replace(" ", "").replace("_", ""))
                if slot and slot not in found:
                    v = rv.strip().strip('"').strip("'").strip()
                    if v:
                        found[slot] = v
    except OSError:
        return None
    if "key" in found and "sec" in found:
        return (found["key"], found["sec"])
    return None


def load_okx_keys():
    """mooja 지정 봇별 OKX 키 매핑(okx_keys.json, .gitignore). 매 호출 파일 읽기(키 변경 즉시 반영)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "okx_keys.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_seeds():
    """봇별 기준금·초기화일시 수동 지정(seeds.json). 봇 stats.json 부재 시 누적/일평균 계산 폴백."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def bot_creds(folder, ex):
    if ex == "OKX":
        # mooja 지정 봇별 키 매핑(okx_keys.json) 최우선 → 각 봇 고유키로 잔고 분리 보장.
        k = load_okx_keys().get(folder)
        if k and k.get("apikey"):
            return ("okx", k["apikey"], k.get("secret", ""), k.get("passphrase", ""))
        # 폴백: 봇 본체와 동일하게 api.md를 단일 출처로 사용(.env보다 우선).
        md = parse_api_md_okx(folder)
        if md:
            return ("okx", md[0], md[1], md[2])
        e = parse_env(os.path.join(BASE, folder, ".env"))
        return ("okx", e.get("OKX_API_KEY", ""), e.get("OKX_SECRET_KEY", ""),
                e.get("OKX_PASSPHRASE", ""))
    # BNC도 api.md를 키 단일 출처로 우선 사용(.env보다 우선) — 봇별 계정 잔고 구분.
    md = parse_api_md_bnc(folder)
    if md:
        return ("binanceusdm", md[0], md[1], "")
    e = parse_env(os.path.join(BASE, folder, ".env"))
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
    poscount = 0   # 거래소 실시간 보유 포지션(contracts≠0) 종목 수
    poslong = 0    # 롱 포지션 수
    posshort = 0   # 숏 포지션 수
    pos_symbols = [] # 거래소 실시간 보유 심볼 목록
    try:
        for p in c.fetch_positions():
            if float(p.get("contracts") or 0) != 0:
                poscount += 1
                side = p.get("side")
                if side == "long":
                    poslong += 1
                elif side == "short":
                    posshort += 1
                v = p.get("unrealizedPnl")
                if v is not None:
                    upnl += float(v)
                sym = p.get("symbol", "").split("/")[0]
                if sym and sym not in pos_symbols:
                    pos_symbols.append(sym)
    except Exception:
        pass
    return {"balance": usdt.get("total"), "free": usdt.get("free"),
            "used": usdt.get("used"), "upnl": round(upnl, 4),
            "poscount": poscount, "poslong": poslong, "posshort": posshort,
            "pos_symbols": pos_symbols,
            "ok": True, "err": None}


_ex_cooldown = {}       # cred -> 이 시각(epoch)까지 조회 스킵 (레이트리밋 백오프)
_ex_backoff = {}        # cred -> 현재 백오프 초
_ex_last_fetch = {}     # cred -> 마지막 조회 epoch (거래소별 갱신 주기 제어)
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
            # 거래소별 조회 주기: 바이낸스는 장주기(BNC_REFRESH_SEC)로만 두드려 IP ban/레이트리밋 회피.
            interval = BNC_REFRESH_SEC if cred[0] == "binanceusdm" else EX_REFRESH_SEC
            if now - _ex_last_fetch.get(cred, 0) < interval:
                continue   # 아직 이 거래소의 갱신 주기 전 → 직전 캐시 유지
            if not cred[1]:
                r = {"ok": False, "err": "API 키 없음"}
            elif _ex_cooldown.get(cred, 0) > now:
                continue   # 레이트리밋 쿨다운 중 → 조회 스킵(직전 값 유지, 더 안 두드림)
            else:
                _ex_last_fetch[cred] = now   # 성공/실패 무관 기록 → 다음 주기까지 안 두드림
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
    # port로 정확하게 봇 ID 추출, 포트-폴더 매칭 명시
    bot_id = str(port)  # port 8401 → bot_id "8401"
    d = os.path.join(BASE, folder, "data")
    r = {"name": bot_id, "folder": folder, "port": port, "ex": ex,
         "alive": port_alive(port), "daily": None, "total": None, "wins": 0,
         "losses": 0, "seed": None, "perf_start": None, "orders_today": 0,
         "total_trades": 0, "age_min": None, "positions": [], "trades": []}

    # 앱 메모리 상태 우선 시도: /tmp/bot_<port>_state.json (앱의 실시간 메모리)
    memory_state_path = f"/tmp/bot_{port}_state.json"
    sp = memory_state_path if os.path.exists(memory_state_path) else os.path.join(d, "stats.json")

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
    # 봇 stats.json이 없어 기준금(seed)·초기화일시를 못 읽으면 seeds.json(mooja 수동 지정)으로 폴백.
    if r["seed"] is None or r["seed"] == 0:
        sd = load_seeds().get(folder)
        if sd:
            r["seed"] = sd.get("seed")
            r["perf_start"] = r["perf_start"] or sd.get("perf_start")
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
    r["since_pnl"] = m["since_pnl"]   # 초기화 이후 실현손익(봇 앱 누적손익)
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
    if not r.get("positions") and r.get("ex_pos_symbols"):
        r["positions"] = r["ex_pos_symbols"]

    # 누적 수익률 = (현재 총잔고 - 초기화 잔고) / 초기화 잔고  ← 봇 대시보드 툴팁과 동일
    #   일시   = perf_start_time(stats.json),  초기화 잔고 = seed_money(stats.json)
    #   현재 총잔고 = 거래소 실시간 잔고. 조회 실패 시 실현손익 기준으로 폴백.
    days = bot_days(r["perf_start"])
    r["days"] = round(days, 2)
    if r["seed"]:
        # 봇 앱과 동일하게 '실제 잔고 변화 ÷ 기준금' 누적 (수수료·펀딩 반영된 실잔고 기준).
        #   조회 실패 시에만 실현손익(total)으로 폴백.
        if r.get("ex_ok") and r.get("ex_balance") is not None:
            r["cum_delta"] = round(r["ex_balance"] - r["seed"], 4)
            r["cum_basis"] = "balance"
        else:
            r["cum_delta"] = round(r["total"] or 0, 4)
            r["cum_basis"] = "pnl"
        r["cum_ret"] = round(r["cum_delta"] / r["seed"] * 100, 2)
        r["daily_ret"] = round(r["cum_ret"] / days, 2)
    else:
        r["cum_ret"] = r["daily_ret"] = r["cum_delta"] = None
        r["cum_basis"] = None
    # 보유 여부 = 거래소 실제 증거금 사용(ex_used>0) 기준. 조회 실패 시에만 active_positions 파일 폴백.
    # (봇이 청산 후 active_positions.json을 안 지워 생기는 '유령 포지션' 오집계 방지 — 예: 8501)
    # 보유 판정: 거래소 증거금(ex_used) 기준이 가장 정확.
    #   거래소 조회 실패(ban·레이트리밋 등 ex_ok=False)면 active_positions.json은
    #   유령(청산 후 미삭제) 위험이 커서 보유 근거로 쓰지 않는다 → None('미확인').
    #   (예: 8409가 바이낸스 IP ban 중 청산했는데 파일엔 옛 포지션이 남아 보유중 오표시되던 문제)
    if r.get("ex_ok"):
        r["holding"] = (r.get("ex_used") or 0) > 0.02 or (r.get("ex_poscount") or 0) > 0 or len(r.get("positions") or []) > 0
    else:
        r["holding"] = None                          # 거래소 미확인
    return r


def bot_days(perf_start):
    try:
        t0 = time.mktime(time.strptime(perf_start, "%Y-%m-%d %H:%M:%S"))
        return max(1.0, (time.time() - t0) / 86400)
    except (TypeError, ValueError):
        return 1.0


def collect():
    bots = [bot_status(*b) for b in BOTS]
    # 합산 누적 수익률 = (Σ현재 총잔고 - 기준금) / 기준금
    #   기준금 = SEED_OVERRIDE(mooja 지정 고정값) 우선, 없으면 봇 seed 자동합산.
    #   현재 총잔고는 거래소 실시간 잔고, 조회 실패 봇은 seed+실현손익으로 폴백.
    # 봇별 현재 잔고·기준금을 함께 합산. 기준금(seed)이 없는 봇(stats.json 미생성 등)은
    # 현재 잔고를 기준금으로 간주(누적 0% 중립) → seed 누락으로 전체 누적이 폭등하는 왜곡 방지.
    assets = 0.0
    seed = 0.0
    for b in bots:
        bal = b["ex_balance"] if (b.get("ex_ok") and b.get("ex_balance") is not None) \
              else ((b["seed"] or 0) + (b["total"] or 0))
        bseed = b["seed"] if b["seed"] else bal   # seed 없으면 잔고=기준금(중립)
        assets += bal
        seed += bseed
    if SEED_OVERRIDE:
        seed = SEED_OVERRIDE
    days = max([bot_days(b["perf_start"]) for b in bots] or [1.0])
    # 합산 누적 = (Σ현재잔고 − Σ기준금) ÷ Σ기준금 (봇 앱과 동일한 실잔고 변화 기준, 수수료·펀딩 반영).
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
        "with_positions": sum(1 for b in bots if b["holding"] is True),
        "no_positions": [b["name"] for b in bots if b["holding"] is False],
        "unknown_positions": [b["name"] for b in bots if b["holding"] is None],  # 거래소 미확인(ban 등)
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
           "bots": {b["name"]: round((b.get("total") or 0) + (b.get("seed") or 0), 2) for b in data["bots"]}}
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


_btc_cache = {}         # tf -> (epoch_fetched, candles[[ts_ms, close], ...])
_btc_lock = threading.Lock()
_btc_client = None
BTC_TF_MS = {"1m": 60000, "5m": 300000, "15m": 900000,
             "1h": 3600000, "4h": 14400000, "1d": 86400000, "1M": 2592000000}


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
            body = json.dumps(collect(), ensure_ascii=False).encode()
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


def discord_loop():
    """매 1분 전체 일평균수익률 요약을 디스코드로 발송 (8888 보유 집계 기반)."""
    import discord_alert
    time.sleep(35)   # 거래소 캐시(EX_CACHE) 워밍업 후 첫 발송 (콜드값 발송 방지)
    while True:
        t0 = time.time()
        try:
            data = collect(); t1 = time.time()
            ok, info = discord_alert.tick(data); t2 = time.time()
            print(f"[DISCORD] {time.strftime('%H:%M:%S')} ok={ok} {info} "
                  f"collect={t1-t0:.1f}s post={t2-t1:.1f}s", flush=True)
        except Exception as e:
            print(f"[DISCORD] {time.strftime('%H:%M:%S')} 예외: {str(e)[:150]}", flush=True)
        # 작업 소요를 빼고 60초 주기 유지 → 발송 간격이 정확히 1분이 되도록 보정
        time.sleep(max(1, 60 - (time.time() - t0)))


if __name__ == "__main__":
    threading.Thread(target=exchange_loop, daemon=True).start()
    threading.Thread(target=snapshot_loop, daemon=True).start()
    threading.Thread(target=asset_loop, daemon=True).start()   # [B안] 총자산 1분 기록
    threading.Thread(target=discord_loop, daemon=True).start()  # 디스코드 1분 요약 알림
    print(f"8888 통합 관제 대시보드: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
