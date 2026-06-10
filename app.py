#!/usr/bin/env python3
"""
8888 — 자동매매봇 통합 관제 대시보드
10개 봇(8401~8409, 8501)의 data/ 파일을 읽기 전용으로 집계해 한 화면에 표시.
의존성 없음(표준라이브러리만). 실행: python3 app.py  →  http://localhost:8888
"""
import csv
import io
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "/Users/l/project"
PORT = 8888
STALE_MIN = 60          # stats.json 갱신이 이보다 오래되면 '지연' 상태
FEED_LIMIT = 15         # 통합 체결 피드 최대 건수
TAIL_BYTES = 16384      # trade_history.csv 끝에서 읽을 바이트 수

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


def tail_trades(path, n=5):
    """trade_history.csv 끝부분만 읽어 최근 n건 반환 (전체 파일 로드 회피)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            chunk = f.read().decode("utf-8-sig", errors="replace")
        lines = [ln for ln in chunk.splitlines() if ln.strip()]
        if size > TAIL_BYTES and lines:
            lines = lines[1:]  # 잘린 첫 줄 버림
        rows = list(csv.reader(io.StringIO("\n".join(lines))))
        rows = [r for r in rows if len(r) >= 8 and not r[0].startswith("﻿시간") and r[0] != "시간"]
        out = []
        for r in rows[-n:]:
            try:
                pnl = float(r[6]) if r[6] not in ("", "0", "0.0") else 0.0
            except ValueError:
                pnl = 0.0
            out.append({"time": r[0], "symbol": r[1].split("/")[0], "type": r[2],
                        "side": r[3], "pnl": round(pnl, 4)})
        return out
    except OSError:
        return []


def bot_status(folder, port, ex):
    d = os.path.join(BASE, folder, "data")
    r = {"name": folder.split("_")[0], "folder": folder, "port": port, "ex": ex,
         "alive": port_alive(port), "daily": None, "total": None, "wins": 0,
         "losses": 0, "seed": None, "age_min": None, "positions": [], "trades": []}
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
        r["age_min"] = round((time.time() - os.path.getmtime(sp)) / 60, 1)
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(d, "active_positions.json"), encoding="utf-8") as f:
            r["positions"] = [k.split("/")[0] for k in json.load(f)]
    except (OSError, ValueError):
        pass
    r["trades"] = tail_trades(os.path.join(d, "trade_history.csv"))
    return r


def run_days(bots):
    """가장 이른 perf_start_time부터의 경과일수 (최소 1일, 단순평균용)."""
    ts = []
    for b in bots:
        try:
            ts.append(time.mktime(time.strptime(b.get("perf_start"), "%Y-%m-%d %H:%M:%S")))
        except (TypeError, ValueError):
            pass
    if not ts:
        return 1.0
    return max(1.0, (time.time() - min(ts)) / 86400)


def collect():
    bots = [bot_status(*b) for b in BOTS]
    feed = sorted((dict(t, bot=b["name"]) for b in bots for t in b["trades"]),
                  key=lambda t: t["time"], reverse=True)[:FEED_LIMIT]
    total = sum(b["total"] or 0 for b in bots)
    seed = sum(b["seed"] or 0 for b in bots)
    days = run_days(bots)
    cum_ret = round(total / seed * 100, 2) if seed else None
    summary = {
        "assets": round(seed + total, 2),          # 총 자산 = 시작잔고 + 실현손익
        "cum_ret": cum_ret,                        # 누적수익률 %
        "daily_ret": round(cum_ret / days, 2) if cum_ret is not None else None,
        "days": round(days, 1),
        "alive": sum(1 for b in bots if b["alive"]),
        "count": len(bots),
        "stale": [b["name"] for b in bots
                  if b["age_min"] is not None and b["age_min"] > STALE_MIN],
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    return {"summary": summary, "bots": bots, "feed": feed, "stale_min": STALE_MIN}


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
    print(f"8888 통합 관제 대시보드: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
