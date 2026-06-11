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

BASE = "/Users/l/project"
PORT = 8888
STALE_MIN = 60          # stats.json 갱신이 이보다 오래되면 '지연' 상태
FEED_LIMIT = 15         # 통합 체결 피드 최대 건수
TAIL_BYTES = 16384      # 체결 피드용 trade_history.csv 끝에서 읽을 바이트
WL_TAIL_BYTES = 131072  # 당일 승률 계산용 (당일 청산을 모두 포함하도록 넉넉히)
EX_REFRESH_SEC = 15     # 거래소 잔고/포지션 캐시 갱신 주기

BOTS = [
    ("8401_okx", 8401, "OKX"), ("8402_okx", 8402, "OKX"), ("8403_okx", 8403, "OKX"),
    ("8404_okx", 8404, "OKX"), ("8405_okx", 8405, "OKX"), ("8406_okx", 8406, "OKX"),
    ("8407_bnc", 8407, "BNC"), ("8408_bnc", 8408, "BNC"), ("8409_bnc", 8409, "BNC"),
    ("8501_bnc", 8501, "BNC"),
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


def hist_metrics(path, perf_start):
    """봇 대시보드와 동일하게 trade_history.csv에서 당일/누적 지표 재계산.
    - 금일 실현 손익 = Σ(청산 수익), 경계 = max(오늘 00:00 KST, perf_start). 행 단위 합산.
    - 당일/누적 주문·승률 = order_id별로 묶어 합산 > 0 승 / < 0 패 (봇 방식).
    """
    today0 = time.strftime("%Y-%m-%d 00:00:00")
    ps = (perf_start or "")[:19]
    b_today = max(today0, ps) if ps else today0
    b_since = ps or today0
    exits = _load_exits(path)
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
    return {"today_pnl": round(today_pnl, 4), "today_w": tw, "today_l": tl,
            "since_w": sw, "since_l": sl, "since_orders": sw + sl}


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
        strategy = live or cfg.get("STRATEGY_MODE") or cfg.get("STRATEGY_TYPE") or strategy_map.get(folder, "—")
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
    return ("binanceusdm", e.get("BINANCE_API_KEY", ""), e.get("BINANCE_SECRET_KEY", ""), "")


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


def exchange_loop():
    while True:
        creds = {}
        for folder, _port, ex in BOTS:
            creds.setdefault(bot_creds(folder, ex), []).append(folder)
        for cred, folders in creds.items():
            if not cred[1]:
                r = {"ok": False, "err": "API 키 없음"}
            else:
                try:
                    r = fetch_account(cred)
                except Exception as e:
                    r = {"ok": False, "err": str(e)[:120]}
            for f in folders:
                EX_CACHE[f] = r
        time.sleep(EX_REFRESH_SEC)


# ── 봇별 파일 기반 지표 ──────────────────────────────────────────────

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
    r["config"] = read_bot_config(folder)
    # 금일 실현 손익·당일/누적 주문·승률을 봇 화면과 동일하게 trade_history에서 재계산
    m = hist_metrics(hist, r["perf_start"])
    r["today_pnl"] = m["today_pnl"]            # 금일 실현 손익 (봇 화면값)
    r["today_w"], r["today_l"] = m["today_w"], m["today_l"]
    r["orders_today"] = m["today_w"] + m["today_l"]
    r["since_w"], r["since_l"] = m["since_w"], m["since_l"]
    r["since_orders"] = m["since_orders"]
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
    return r


def bot_days(perf_start):
    try:
        t0 = time.mktime(time.strptime(perf_start, "%Y-%m-%d %H:%M:%S"))
        return max(1.0, (time.time() - t0) / 86400)
    except (TypeError, ValueError):
        return 1.0


def collect():
    bots = [bot_status(*b) for b in BOTS]
    # 합산 누적 수익률 = (Σ현재 총잔고 - Σ초기화 잔고) / Σ초기화 잔고  ← 티커별과 동일 기준
    #   현재 총잔고는 거래소 실시간 잔고, 조회 실패 봇은 seed+실현손익으로 폴백.
    seed = sum(b["seed"] or 0 for b in bots)
    assets = 0.0
    for b in bots:
        if b.get("ex_ok") and b.get("ex_balance") is not None:
            assets += b["ex_balance"]
        else:
            assets += (b["seed"] or 0) + (b["total"] or 0)
    days = max([bot_days(b["perf_start"]) for b in bots] or [1.0])
    cum_ret = round((assets - seed) / seed * 100, 2) if seed else None
    summary = {
        "assets": round(assets, 2),
        "cum_ret": cum_ret,
        "cum_delta": round(assets - seed, 2),
        "daily_ret": round(cum_ret / days, 2) if cum_ret is not None else None,
        "days": round(days, 1),
        "alive": sum(1 for b in bots if b["alive"]),
        "count": len(bots),
        "with_positions": sum(1 for b in bots if b["positions"]),
        "no_positions": [b["name"] for b in bots if not b["positions"]],
        "stale": [b["name"] for b in bots
                  if b["age_min"] is not None and b["age_min"] > STALE_MIN],
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    return {"summary": summary, "bots": bots, "stale_min": STALE_MIN}


with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html"), encoding="utf-8") as f:
    HTML = f.read()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/status"):
            body = json.dumps(collect(), ensure_ascii=False).encode()
            ctype = "application/json; charset=utf-8"
        elif self.path == "/" or self.path.startswith("/index"):
            body = HTML.encode()
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
    print(f"8888 통합 관제 대시보드: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
