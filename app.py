#!/usr/bin/env python3
"""
8888 — 자동매매봇 통합 관제 대시보드
10개 봇(8401~8409, 8501)의 data/ 파일 + 거래소 조회 전용 API를 집계해 한 화면에 표시.
- 봇 폴더는 읽기 전용 (.env의 키도 읽기만, 파일 수정 없음)
- 거래소 호출은 fetch_balance / fetch_positions 조회 전용. 주문 함수 없음.
실행: python3 app.py  →  http://localhost:8888
"""
import asyncio
import csv
from datetime import datetime
import io
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import shutil

def atomic_save_json(path, data, indent=None):
    """원자적 JSON 파일 저장 (Atomic Write + 안전 .bak 백업 생성)"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_name = os.path.dirname(path)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        bak_path = path + ".bak"
        if os.path.exists(path):
            try:
                shutil.copy2(path, bak_path)
            except Exception:
                pass
        os.replace(tmp_path, path)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise e

def safe_load_json(path, default=None):
    """JSON 파일 안전 로드 (파일 파손 시 .bak 자동 롤백 로드)"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        bak_path = path + ".bak"
        if os.path.exists(bak_path):
            try:
                with open(bak_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                atomic_save_json(path, data)
                return data
            except Exception:
                pass
        return default

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8888
STALE_MIN = 60          # stats.json 갱신이 이보다 오래되면 '지연' 상태
FEED_LIMIT = 15         # 통합 체결 피드 최대 건수
TAIL_BYTES = 16384      # 체결 피드용 trade_history.csv 끝에서 읽을 바이트
WL_TAIL_BYTES = 131072  # 당일 승률 계산용 (당일 청산을 모두 포함하도록 넉넉히)
EX_REFRESH_SEC = 15     # 거래소(OKX) 잔고/포지션 캐시 갱신 주기
BNC_REFRESH_SEC = 30    # 바이낸스(BNC) 30초 동기화 — 실시간 자산 및 수익률 반영
SEED_OVERRIDE = None     # 전체 기준금(초기자본금 합). None=각 봇 stats.json seed_money 실시간 합산.
                         # 봇 재초기화 시 seed_money가 갱신되므로 고정값이 아니라 자동합산해야
                         # 봇별 누적수익률과 전체 누적수익률이 항상 정합(전체 cum_delta = Σ봇별 cum_delta).

BOTS = [
    ("8401", 8401, "OKX"),
    ("8402", 8402, "OKX"),
    ("8403", 8403, "OKX"),
    ("8404", 8404, "OKX"),
    ("8405", 8405, "OKX"),
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
    """trade_history.csv에서 각 주문ID(order ID)별 최초 출현 시각을 진입 시각으로 파싱. mtime 캐시."""
    try:
        mt = os.path.getmtime(path)
        sz = os.path.getsize(path)
    except OSError:
        return []
    c = _ENTRY_CACHE.get(path)
    if c and c[0] == mt and c[1] == sz:
        return c[2]
    oid_min_ts = {}
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for i, r in enumerate(csv.reader(f)):
                if len(r) < 3:
                    continue
                ts = r[0].strip()[:19]
                if not ts[:4].isdigit():
                    continue
                oid = r[10].strip() if len(r) > 10 and r[10].strip() else f"unk_entry_{ts}_{i}"
                if oid not in oid_min_ts or ts < oid_min_ts[oid]:
                    oid_min_ts[oid] = ts
        entries = sorted([(ts, oid) for oid, ts in oid_min_ts.items()])
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


def hist_metrics(path, perf_start, pos_count=0):
    """봇 대시보드와 동일하게 trade_history.csv에서 당일/누적 지표 재계산.
    - 금일 실현 손익 = Σ(청산 수익), 경계 = 오늘 00:00 KST.
    - 당일/누적 주문·승률 = order_id별로 묶어 합산 > 0 승 / < 0 패. (부분청산 승패 왜곡 방지)
    - 24시간 내 진입 수 = 현재 시각 기준 직전 24시간 롤링 윈도우 내 진입 기록 수.
    """
    today0 = time.strftime("%Y-%m-%d 00:00:00")
    ps = (perf_start or "")[:19]
    exits = _load_exits(path)
    entries = _load_entries(path)

    # 옵션 A: 사용자가 설정한 초기화 시점(ps)이 없을 때만 CSV의 가장 과거 시각을 기준점으로 사용
    if not ps and (entries or exits):
        all_ts = [x[0] for x in entries] + [x[0] for x in exits]
        if all_ts:
            ps = min(all_ts)

    b_today = today0  # 초기화 시점과 무관하게 당일(00:00 이후) 모든 수익 집계
    b_since = ps or today0

    today_pnl = 0.0
    today_grp, since_grp = {}, {}
    entry_dict = {}
    
    # OID 누락 방지 (빈 문자열이면 가상 ID 부여)
    for i, (ts, oid) in enumerate(entries):
        if not oid:
            oid = f"unk_entry_{ts}_{i}"
            entries[i] = (ts, oid)
        if oid not in entry_dict:
            entry_dict[oid] = ts  # 첫 진입 시각 기준

    holding_times = []
    for i in range(len(exits)):
        ts, pnl, oid = exits[i]
        if not oid:
            oid = f"unk_exit_{ts}_{i}"  # 빈 OID 누락 방지
            exits[i] = (ts, pnl, oid)
            
        if ts >= b_since:
            since_grp[oid] = since_grp.get(oid, 0.0) + pnl
            if oid in entry_dict:
                try:
                    t_in = time.mktime(time.strptime(entry_dict[oid], "%Y-%m-%d %H:%M:%S"))
                    t_out = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
                    ht = max(0, t_out - t_in)
                    holding_times.append(ht)
                except Exception:
                    pass
            if ts >= b_today:
                today_pnl += pnl
                today_grp[oid] = today_grp.get(oid, 0.0) + pnl

    # 부분청산된 경우, 오늘 판정은 해당 거래의 '전체 누적손익(since_grp)'을 기준으로 하여 승패 왜곡 방지
    tw = sum(1 for oid, v in today_grp.items() if since_grp.get(oid, v) > 0)
    tl = sum(1 for oid, v in today_grp.items() if since_grp.get(oid, v) < 0)
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

    # SQN (System Quality Number) 산출
    # SQN = (기대수익 / 손익의 표준편차) * sqrt(거래수)
    sqn = None
    if n_grp > 1 and expectancy is not None:
        import math
        pnls = list(since_grp.values())
        mean_pnl = sum(pnls) / n_grp
        variance = sum((p - mean_pnl)**2 for p in pnls) / (n_grp - 1)
        std_dev = math.sqrt(variance)
        if std_dev > 0:
            sqn = round((expectancy / std_dev) * math.sqrt(n_grp), 2)

    # 소르티노 비율 (Sortino Ratio) 산출
    # Sortino = 기대수익 / 하방편차(Downside Deviation)
    sortino = None
    if n_grp > 0 and expectancy is not None and losses:
        import math
        downside_variance = sum(l**2 for l in losses) / n_grp
        down_dev = math.sqrt(downside_variance)
        if down_dev > 0:
            sortino = round(expectancy / down_dev, 2)

    # Time-in-Market 효율성 지표
    total_holding_sec = sum(holding_times)
    avg_holding_hours = round((total_holding_sec / len(holding_times)) / 3600, 2) if holding_times else None
    profit_per_hour = None
    if total_holding_sec > 0:
        profit_per_hour = round((gross_win - gross_loss) / (total_holding_sec / 3600), 4)

    # 기간별 진입 수 = 직전 N시간 롤링 윈도우 내 실제 진입 건수 (청산 완료 고유 거래 수 + 현재 오픈 포지션 수)
    now = time.time()
    periods = {"1h": 3600, "4h": 14400, "6h": 21600, "12h": 43200, "24h": 86400,
               "48h": 172800, "72h": 259200, "1w": 604800}
    entries_by_period = {}
    for key, secs in periods.items():
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - secs))
        if ps and cutoff < ps:
            cutoff = ps
        # 1. 해당 윈도우 내 실현손익이 0이 아닌 청산 완료된 고유 거래 건수
        period_grp = {}
        for ts, pnl, oid in exits:
            if ts >= cutoff and oid:
                period_grp[oid] = period_grp.get(oid, 0.0) + pnl
        completed_trades = sum(1 for oid, v in period_grp.items() if round(v, 4) != 0.0)
        
        # 2. 해당 윈도우 내에 존재하는 현재 오픈 포지션 건수 (1h는 최근 진입이 있는 경우만 합산)
        if key == "1h":
            recent_open = pos_count if (entries and max(e[0] for e in entries) >= cutoff) else 0
            entries_by_period[key] = completed_trades + recent_open
        else:
            entries_by_period[key] = completed_trades + pos_count

    return {"today_pnl": round(today_pnl, 4), "today_w": tw, "today_l": tl,
            "since_w": sw, "since_l": sl, "since_orders": sw + sl,
            "since_pnl": round(sum(since_grp.values()), 4),   # 초기화 이후 실현손익 = 봇 앱 누적손익
            "profit_factor": profit_factor, "avg_wl": avg_wl, "expectancy": expectancy, "sqn": sqn, "sortino": sortino,
            "avg_holding_hours": avg_holding_hours, "profit_per_hour": profit_per_hour,
            "entries_24h": entries_by_period["24h"], "entries_by_period": entries_by_period,
            "adjusted_perf_start": ps}

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
    """[3단계] 최근 N일 청산 실현손익을 요일×시간대(3시간 8구간)로 집계.
    반환: {"wday_bucket": pnl_sum, ...}  (wday 0=월 … 6=일, bucket 0=00–03 … 7=21–24)
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
        key = "%d_%d" % (st.tm_wday, st.tm_hour // 3)
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
        cfg = safe_load_json(cfg_path, {})
        # 전략명: 하드코딩 override 전면 제거(mooja 지시 2026-06-25) → config STRATEGY_MODE 실시간 우선.
        # 'None'·빈값이면 STRATEGY_TYPE → 실거래 active_positions strategy_type → '—' 순 폴백.
        mode = cfg.get("STRATEGY_MODE")
        if mode in (None, "", "None", "none"):
            mode = None
        live = ""
        try:
            pos = safe_load_json(os.path.join(BASE, folder, "data", "active_positions.json"), {})
            stset = sorted({v.get("strategy_type") for v in pos.values()
                            if isinstance(v, dict) and v.get("strategy_type")})
            live = "/".join(stset)
        except Exception:
            pass
        strategy = mode or cfg.get("STRATEGY_TYPE") or live or "—"
        if strategy == "—":
            if "MACD_FAST" in cfg:
                strategy = "AKMCD + SSL 하이브리드"
            elif len(cfg.get("SYMBOL_WHITELIST", [])) == 7:
                strategy = "메이저 7종 한정 스캔"
            elif len(cfg.get("SYMBOL_WHITELIST", [])) >= 30:
                strategy = "우량 30종목 스캔"
            elif "BB_PERIOD" in cfg:
                strategy = "TTM Squeeze 돌파"
            else:
                strategy = "기본 추세 돌파"
                
        indicators = []
        if cfg.get("EMA_PERIOD"): indicators.append(f"EMA{cfg['EMA_PERIOD']}")
        if cfg.get("RSI_PERIOD"): indicators.append(f"RSI{cfg['RSI_PERIOD']}")
        if cfg.get("MACD_FAST"): indicators.append(f"MACD({cfg['MACD_FAST']},{cfg['MACD_SLOW']})")
        if cfg.get("SSL_PERIOD"): indicators.append(f"SSL{cfg['SSL_PERIOD']}")
        if cfg.get("BB_PERIOD"): indicators.append(f"BB{cfg['BB_PERIOD']}")
        ind_str = ", ".join(indicators) if indicators else "—"

        wl = cfg.get("SYMBOL_WHITELIST", [])
        scan_targets = f"지정 {len(wl)}개" if wl else f"상위 {cfg.get('SCAN_TOP_N', '?')}개"

        use_bf = cfg.get("USE_BLUEFROG")
        if use_bf is None:
            py_path = os.path.join(BASE, folder, "config.py")
            if os.path.exists(py_path):
                try:
                    with open(py_path, encoding="utf-8") as pf:
                        m = re.search(r"USE_BLUEFROG\s*=\s*(True|False)", pf.read())
                        if m:
                            use_bf = (m.group(1) == "True")
                except Exception:
                    pass
        if use_bf is None:
            use_bf = True

        return {
            "leverage": cfg.get("LEVERAGE", "—"),
            "margin_usdt": cfg.get("MARGIN_USDT", "—"),
            "max_positions": cfg.get("MAX_POSITIONS", "—"),
            "stop_loss_pct": f"{cfg.get('STOP_LOSS_PCT', 0)*100:.2f}%",
            "take_profit_pct": f"{cfg.get('TAKE_PROFIT_PCT', 0)*100:.2f}%",
            "timeframe": cfg.get("TIMEFRAME", "—"),
            "indicators": ind_str,
            "strategy": strategy,
            "scan_targets": scan_targets,
            "max_holding_hours": cfg.get("MAX_HOLDING_HOURS", "—"),
            "USE_BLUEFROG": bool(use_bf),
        }
    except (OSError, json.JSONDecodeError, ValueError):
        return {k: "—" for k in ["leverage", "margin_usdt", "max_positions", "stop_loss_pct",
                                  "take_profit_pct", "timeframe", "indicators", "strategy", "scan_targets",
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
    return safe_load_json(path, {})


def load_seeds():
    """봇별 기준금·초기화일시 수동 지정(seeds.json). 봇 stats.json 부재 시 누적/일평균 계산 폴백."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json")
    return safe_load_json(path, {})


def sync_seed_info(folder, seed, perf_start):
    """각 봇 stats.json의 seed와 perf_start가 변경되면 seeds.json에도 실시간 자동 업데이트"""
    if not seed or not perf_start:
        return
    try:
        seeds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seeds.json")
        seeds = load_seeds()
        curr = seeds.get(folder, {})
        if curr.get("seed") != float(seed) or curr.get("perf_start") != str(perf_start):
            seeds[folder] = {"seed": float(seed), "perf_start": str(perf_start)}
            atomic_save_json(seeds_path, seeds, indent=2)
    except Exception:
        pass


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

PERSIST_EX_CACHE_PATH = os.path.join(BASE, "data", "ex_cache_persistent.json")


def _load_persistent_ex_cache():
    try:
        data = safe_load_json(PERSIST_EX_CACHE_PATH, {})
        if isinstance(data, dict):
            EX_CACHE.update(data)
    except Exception:
        pass


def _save_persistent_ex_cache():
    try:
        atomic_save_json(PERSIST_EX_CACHE_PATH, EX_CACHE)
    except Exception:
        pass


_load_persistent_ex_cache()


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
            elif ex_id == "binanceusdm":
                c.options["fetchMarkets"] = ["linear"]
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
                    prev = None
                    for f in folders:
                        c_item = EX_CACHE.get(f)
                        if c_item and c_item.get("balance") is not None:
                            prev = c_item
                            break
                    if prev and prev.get("balance") is not None:
                        r = {**prev, "ok": True, "stale": True, "err": msg}
                    else:
                        r = {"ok": False, "err": msg, "stale": True}
            for f in folders:
                EX_CACHE[f] = r
            _save_persistent_ex_cache()
        time.sleep(EX_REFRESH_SEC)


# ── 봇별 파일 기반 지표 ──────────────────────────────────────────────

_TICKER_CACHE = {}  # symbol -> (mtime, price)


def get_public_price(symbol_short):
    """OKX 퍼블릭 시세 조회 (IP 차단 무관, 인증 0). 15초 캐시."""
    now = time.time()
    c = _TICKER_CACHE.get(symbol_short)
    if c and (now - c[0]) < 15:
        return c[1]
    try:
        import ccxt
        ex = getattr(get_public_price, "_ex", None)
        if ex is None:
            ex = ccxt.okx({"enableRateLimit": True, "timeout": 5000})
            get_public_price._ex = ex
        pair = f"{symbol_short}/USDT:USDT"
        tick = ex.fetch_ticker(pair)
        price = float(tick.get("last") or 0.0)
        if price > 0:
            _TICKER_CACHE[symbol_short] = (now, price)
            return price
    except Exception:
        pass
    return c[1] if c else None


def estimate_bot_upnl(folder, positions):
    """trade_history.csv에서 보유 종목 진입가/수량/방향 추출 후 퍼블릭 시세로 uPNL 실시간 계산."""
    if not positions:
        return 0.0
    hist_path = os.path.join(BASE, folder, "data", "trade_history.csv")
    try:
        if not os.path.exists(hist_path):
            return 0.0
        with open(hist_path, encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.reader(f))
        if not rows:
            return 0.0
        pos_set = set(positions)
        entry_info = {}
        for r in reversed(rows):
            if len(r) >= 6 and r[2] == "진입":
                sym = r[1].split("/")[0].strip()
                if sym in pos_set and sym not in entry_info:
                    try:
                        side = r[3].strip().lower()
                        price = float(r[4])
                        qty = float(r[5])
                        entry_info[sym] = (side, price, qty)
                    except (ValueError, IndexError):
                        pass
        total_upnl = 0.0
        for sym, (side, entry_price, qty) in entry_info.items():
            curr_price = get_public_price(sym)
            if curr_price and entry_price > 0:
                diff = (curr_price - entry_price) if side in ("long", "buy") else (entry_price - curr_price)
                total_upnl += diff * qty
        return round(total_upnl, 4)
    except Exception:
        return 0.0


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


import hashlib

GOLDEN_HASHES = {
    "8401": {
        "bot.py": "66ae45514f5f35dcfacdc854cee9f425a8af57ef88b3ab564f07e8bfe464f1b6",
        "core/strategy.py": "e763290eb4382ecf64f0eada9768d403bc0156006688aa3727a318a291d29d80",
        "core/trader.py": "634017d4d54f8eeb9c8a5f0c72fce9be04ce098f9417ce6c6d689dff193c0cc6",
        "core/engine.py": "28a23a33325096ffb21304890e3b91ac250595cdec825e70206432d5757ae6c2"
    },
    "8402": {
        "bot.py": "71f7dd2d5be721843b2b57055cc94df6c8afd9c1cdf7e455eb131ae478124762",
        "core/strategy.py": "20aeec2414df2256b60944ae4f96212659332a10016a4630f9c424710cf7661d",
        "core/trader.py": "9f43bbb01990f9c960b2bd3424b0731bcdc6341227e39ae968df9938746350f2",
        "core/engine.py": "46fabe0a7d7348cee8968b47a726daaedecdb28a159150a7c1ed432822535635"
    },
    "8403": {
        "bot.py": "7dac57591d2ef0ad0366ccef79aa97e5d0c9bdc99ccf7ea5d6446c4e400cbd81",
        "core/strategy.py": "30664ba53e2102eb990d122085e25461b851f540e90004dfe13eb8fb41cc78b4",
        "core/trader.py": "634017d4d54f8eeb9c8a5f0c72fce9be04ce098f9417ce6c6d689dff193c0cc6",
        "core/engine.py": "e39284086c1db21545728280118c670bdc1d360371ecdf03adcea95c0778132e"
    },
    "8404": {
        "bot.py": "71f7dd2d5be721843b2b57055cc94df6c8afd9c1cdf7e455eb131ae478124762",
        "core/strategy.py": "fc00849f544329a29092c1952d0af654b679881998ebfff7ee212cdcf8872d15",
        "core/trader.py": "06128649e213ae32525277ae04c56533bc62bb71882ac8750993bec9da3cc231",
        "core/engine.py": "8c7a297d8216ba9396d0ecdf714286b96d5c55af901904411d0f40be6a6e43e0"
    },
    "8405": {
        "bot.py": "f5d97ac4b649533f8084286e5695c8dc70cc05c0716dd2f22d7e9e14166d7f2a",
        "core/strategy.py": "db10a58a12bc9b9dc6dfb6e15054a562d6712703dfda12a09b962166d780c687",
        "core/trader.py": "cc3622757083a474528e6944d5cc8a38f339d48e6c6b2c933c422e5ec488466e",
        "core/engine.py": "d1b2fb7fff8f4470a175d15fcbafd2e212043d16aef8735987dc4c4de430a384"
    },
    "8407": {
        "bot.py": "8f6da5469282fae440d680db7ff44821e5305944ecc04d0a6727a0e3b26a23db",
        "core/strategy.py": "44e6af3659348e795236d1cf0a7bc223d46bab4b3e482a53453007f32d197809",
        "core/trader.py": "f8b042a36cfd24a6b4e5823eb57ee08b136083e3d0d37589c41749ac0ceccbf0",
        "core/engine.py": "d1b2fb7fff8f4470a175d15fcbafd2e212043d16aef8735987dc4c4de430a384"
    },
    "8408": {
        "bot.py": "2064a2525bf530da85ef267247483d220735bb60a0c9a969d0c739b9e84a3e79",
        "core/strategy.py": "30664ba53e2102eb990d122085e25461b851f540e90004dfe13eb8fb41cc78b4",
        "core/trader.py": "e2b18aa796e83d14ff10bb3d7da29c4dfdc518755e7fa66247a91af8611ea46c",
        "core/engine.py": "26e94cf7f2c7c078f94c719d7485e9ec0e1d2e7a537c0c0485a7ffdbd94ea19e"
    },
    "8409": {
        "bot.py": "41dc06cc1886a660335c52c5156eade962a162bb3e1e4c6ef46fbb828d2de711",
        "core/strategy.py": "411b1a8ea5902cc511ce06d6d63a6dfd0e0b145e19e549e27b6bba94b7ee695c",
        "core/trader.py": "99765b12b117dcfd5f17db25034fe67f868c9009ddbfa8a9cce496c73ad714e3",
        "core/engine.py": "af53761e8175c8fda6b3db69790af48d6aef9e797a180f2904081851f5cf9306"
    }
}


def bot_status(folder, port, ex):
    # port로 정확하게 봇 ID 추출, 포트-폴더 매칭 명시
    bot_id = str(port)  # port 8401 → bot_id "8401"
    d = os.path.join(BASE, folder, "data")
    r = {"name": bot_id, "folder": folder, "port": port, "ex": ex,
         "alive": port_alive(port), "daily": None, "total": None, "wins": 0,
         "losses": 0, "seed": None, "perf_start": None, "orders_today": 0,
         "total_trades": 0, "age_min": None, "positions": [], "trades": []}

    # 무결성 검사 (Integrity Checker) - 토글(integrity_toggle.json)이 켜져 있을 때만 실행
    # (주의: 자동 모드 스위칭으로 USE_BLUEFROG 등이 동적 변동되는 config.json은 검사 대상에서 제외하고 4대 핵심 소스코드만 100% SHA-256 엄중 대조)
    r["golden_compromised"] = False
    r["compromised_files"] = []
    state_file = os.path.join(BASE, "data", "integrity_toggle.json")
    is_integrity_enabled = safe_load_json(state_file, {"enabled": True}).get("enabled", True)

    if is_integrity_enabled and (bot_id in GOLDEN_HASHES):
        for tfile, expected_hash in GOLDEN_HASHES[bot_id].items():
            if tfile == "config.json":
                continue
            fpath = os.path.join(BASE, folder, tfile)
            if os.path.exists(fpath):
                try:
                    with open(fpath, "rb") as f:
                        f_content = f.read().replace(b"\r\n", b"\n")
                        h = hashlib.sha256(f_content).hexdigest()
                        if h != expected_hash:
                            r["golden_compromised"] = True
                            r["compromised_files"].append(tfile)
                except Exception:
                    pass

    # 실시간 메모리 / stats.json 데이터 로딩
    sp = os.path.join(d, "stats.json")
    try:
        s = safe_load_json(sp, {})
        r["daily"] = s.get("daily_pnl_usdt")
        r["total"] = s.get("total_pnl_usdt")
        r["wins"] = s.get("total_wins") or 0
        r["losses"] = s.get("total_losses") or 0
        r["seed"] = s.get("seed_money")
        r["perf_start"] = s.get("perf_start_time")
        r["orders_today"] = s.get("orders_today") or 0
        r["total_trades"] = s.get("total_trades") or 0
        if os.path.exists(sp):
            r["age_min"] = round((time.time() - os.path.getmtime(sp)) / 60, 1)
    except Exception:
        pass

    # 기준금(seed)·초기화일시(perf_start)는 stats.json의 실시간 seed_money/perf_start_time을 1순위로 사용.
    # stats.json에 값이 없거나 0이면 seeds.json을 폴백으로 사용.
    sd = load_seeds().get(folder)
    if not r["seed"] or float(r["seed"] or 0) <= 0:
        if sd and sd.get("seed") and float(sd.get("seed")) > 0:
            r["seed"] = float(sd.get("seed"))
    if not r["perf_start"]:
        if sd and sd.get("perf_start"):
            r["perf_start"] = sd.get("perf_start")
    sync_seed_info(folder, r.get("seed"), r.get("perf_start"))
    try:
        pos_data = safe_load_json(os.path.join(d, "active_positions.json"), {})
        r["positions"] = [k.split("/")[0] for k in pos_data]
    except Exception:
        pass
    hist = os.path.join(d, "trade_history.csv")
    r["trades"] = tail_trades(hist)
    # ⏸무진입 = 마지막 진입 이후 경과, ⏸무포지션 = 마지막 청산 이후(현재 무포지션일 때) 경과
    r["last_entry"], r["last_flat"] = last_entry_exit(hist, r["perf_start"])
    r["config"] = read_bot_config(folder)
    r["app_debug"] = app_debug_time(folder)   # 앱 최종 디버깅(app.py+core/*.py 최신 mtime)
    r.update({"ex_" + k: v for k, v in EX_CACHE.get(folder, {"ok": False, "err": "조회 전"}).items()})
    if not r.get("positions") and r.get("ex_pos_symbols"):
        r["positions"] = r["ex_pos_symbols"]

    # 로컬 매매 엔진(active_positions.json)에 포지션이 비어 있으면(len(positions) == 0),
    # 거래소 API 조회가 실패(ok=False)했거나 과거 캐시가 지연(stale=True) 상태로 덮어씌워졌더라도
    # 유령 포지션(과거 증거금/포지션 수)이나 ?/? 표기가 나오지 않도록 0/무포지션으로 확정.
    if r.get("positions") is not None and len(r["positions"]) == 0:
        if not r.get("ex_ok") or r.get("ex_stale"):
            r["ex_poscount"] = 0
            r["ex_poslong"] = 0
            r["ex_posshort"] = 0
            r["ex_used"] = 0.0
            r["ex_pos_symbols"] = []
            r["holding"] = False
    elif r.get("positions") is not None and len(r["positions"]) > 0:
        if not r.get("ex_ok") or r.get("ex_stale"):
            # 로컬 매매 엔진엔 포지션이 존재하는데 거래소 조회가 실패/지연된 경우,
            # active_positions.json을 폴백 기준으로 삼아 최소한의 포지션 개수 및 보유 상태 반영
            if r.get("ex_poscount") is None or not r.get("ex_ok"):
                r["ex_poscount"] = len(r["positions"])
                r["ex_poslong"] = len(r["positions"])
                r["ex_posshort"] = 0
                r["holding"] = True

    pos_count = (r.get("ex_poslong", 0) or 0) + (r.get("ex_posshort", 0) or 0) if r.get("ex_poslong") is not None else len(r.get("positions") or [])
    m = hist_metrics(hist, r["perf_start"], pos_count=pos_count)
    r["perf_start"] = m.get("adjusted_perf_start", r["perf_start"])  # 과거 복구 데이터 반영
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
    r["sqn"] = m.get("sqn")
    r["sortino"] = m.get("sortino")
    r["avg_holding_hours"] = m.get("avg_holding_hours")
    r["profit_per_hour"] = m.get("profit_per_hour")
    dd = drawdown_metrics(hist, r["perf_start"], r["seed"])
    r["max_dd"] = dd["max_dd"]                 # [2단계] 최대 낙폭(누적, %)
    r["today_dd"] = dd["today_dd"]             # [2단계] 당일 낙폭(%)
    r["hm_grid"] = heatmap_grid(hist, r["perf_start"])   # [3단계] 요일×시간대 실현손익(7일)

    # 누적 수익률 = (현재 총잔고 - 초기화 잔고) / 초기화 잔고  ← 봇 대시보드 툴팁과 동일
    #   일시   = perf_start_time(stats.json),  초기화 잔고 = seed_money(stats.json)
    #   현재 총잔고 = 거래소 실시간 잔고. 조회 실패 시 실현손익 기준으로 폴백.
    days = bot_days(r["perf_start"])
    r["days"] = round(days, 2)
    if r["seed"]:
        # 실현손익(since_pnl/total) 기준으로 누적손익 및 일평균수익률 산출 (미실현·수수료 튀기 현상 방지)
        r["cum_delta"] = round(r.get("since_pnl", r["total"]) or 0, 4)
        r["cum_basis"] = "pnl"
        r["cum_ret"] = round(r["cum_delta"] / r["seed"] * 100, 2)
        eff_days = max(days, 1.0)
        r["daily_ret"] = round(r["cum_ret"] / eff_days, 2)
    else:
        r["cum_ret"] = r["daily_ret"] = r["cum_delta"] = None
        r["cum_basis"] = None
    # 보유 여부 = 거래소 실제 증거금 사용(ex_used>0) 기준. 조회 실패 시에만 active_positions 파일 폴백.
    # (봇이 청산 후 active_positions.json을 안 지워 생기는 '유령 포지션' 오집계 방지 — 예: 8501)
    # 보유 판정: 거래소 증거금(ex_used) 기준이 가장 정확.
    #   거래소 조회 실패(ban·레이트리밋 등 ex_ok=False)나 stale일 경우 로컬 엔진(active_positions.json) 교차 검증 반영.
    if r.get("holding") is None:
        if r.get("ex_ok") and not r.get("ex_stale"):
            r["holding"] = (r.get("ex_used") or 0) > 0.02 or (r.get("ex_poscount") or 0) > 0
        else:
            r["holding"] = len(r["positions"]) > 0 if r.get("positions") is not None else None
    
    r["metrics"] = calc_bot_metrics(folder, r)
    return r


def calc_bot_metrics(folder, bot_dict):
    """초기화 이후 ~ 현재 봇 실자산 잔고($) 기반 최고/평균/최저/현재 일평균 수익률 및 일시 정밀 계산"""
    try:
        seed = float(bot_dict.get("seed") or 10.0)
        perf_start = bot_dict.get("perf_start") or ""
        days = float(bot_dict.get("days") or 1.0)
        
        try:
            p_clean = str(perf_start).replace("T", " ")[:19]
            t0 = time.mktime(time.strptime(p_clean, "%Y-%m-%d %H:%M:%S"))
        except Exception:
            t0 = time.time() - (86400 * days)
            p_clean = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0))

        now_epoch = int(time.time())
        start_epoch = max(now_epoch - 86400 * 7, int(t0))
        
        d = os.path.join(BASE, folder, "data")
        csv_path = os.path.join(d, "trade_history.csv")
        exits = sorted(_load_exits(csv_path), key=lambda x: x[0]) if os.path.exists(csv_path) else []
        if p_clean:
            exits = [e for e in exits if e[0] >= p_clean]

        snap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots.json")
        snaps = safe_load_json(snap_path, [])

        records = []
        for t in range(start_epoch, now_epoch + 1, 300):
            t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
            t_short = time.strftime("%Y-%m-%d %H:%M", time.localtime(t))
            
            found_asset = None
            for s in snaps:
                st_ts = s.get("ts") or ""
                if st_ts and st_ts[:15] == t_short[:15]:
                    bots = s.get("bots") or {}
                    if isinstance(bots, dict) and folder in bots:
                        found_asset = float(bots[folder])
                        break
            
            if found_asset is None:
                cum_pnl = sum(pnl for ex_ts, pnl, oid in exits if ex_ts <= t_str)
                found_asset = seed + cum_pnl

            cum_delta = found_asset - seed
            cum_ret = (cum_delta / seed) * 100.0 if seed else 0.0
            cur_days = max(1.0, (t - t0) / 86400.0)
            daily_ret = round(cum_ret / cur_days, 2)
            records.append((t_str, daily_ret, found_asset, cum_delta, round(cur_days, 2)))

        if not records:
            return None

        vals = [rec[1] for rec in records]
        max_val = max(vals)
        min_val = min(vals)
        avg_val = round(sum(vals) / len(vals), 2)
        
        max_recs = [rec for rec in records if rec[1] == max_val]
        min_recs = [rec for rec in records if rec[1] == min_val]
        
        curr_ex_bal = bot_dict.get("ex_balance")
        if curr_ex_bal is None or float(curr_ex_bal) <= 0:
            curr_ex_bal = records[-1][2]
        curr_dr = bot_dict.get("daily_ret") if bot_dict.get("daily_ret") is not None else records[-1][1]

        step = max(1, len(records) // 60)
        history = [rec[1] for rec in records[::step]]
        if not history or history[-1] != curr_dr:
            history.append(curr_dr)

        return {
            "seed": seed,
            "perf_start": p_clean,
            "days": round(days, 2),
            "curr_bal": round(float(curr_ex_bal), 2),
            "max_dr": max_val,
            "max_dr_ts": max_recs[-1][0],
            "max_dr_bal": round(max_recs[-1][2], 2),
            "avg_dr": avg_val,
            "min_dr": min_val,
            "min_dr_ts": min_recs[0][0],
            "min_dr_bal": round(min_recs[0][2], 2),
            "curr_dr": curr_dr,
            "history": history
        }
    except Exception as e:
        print(f"[METRICS ERR] {folder}: {e}")
        return None


def bot_days(perf_start):
    try:
        t0 = time.mktime(time.strptime(perf_start, "%Y-%m-%d %H:%M:%S"))
        return max(1.0, (time.time() - t0) / 86400)
    except (TypeError, ValueError):
        return 1.0


EXCLUDED_BOTS = [
    ("8403", 8403, "OKX"),
    ("8407", 8407, "BNC"),
    ("8409", 8409, "BNC"),
]


def collect_bots(bot_tuples):
    bots = [bot_status(*b) for b in bot_tuples]
    assets = 0.0
    seed = 0.0
    for b in bots:
        bal = b["ex_balance"] if (b.get("ex_ok") and b.get("ex_balance") is not None) \
              else ((b["seed"] or 0) + (b["total"] or 0))
        bseed = b["seed"] if b["seed"] else bal
        assets += bal
        seed += bseed
    days = max([bot_days(b["perf_start"]) for b in bots] or [1.0])
    cum_ret = round((assets - seed) / seed * 100, 2) if seed else None
    
    valid_bots = [b for b in bots if b.get("daily_ret") is not None and b.get("seed")]
    if valid_bots:
        tot_s = sum(b["seed"] for b in valid_bots)
        daily_ret = round(sum(b["daily_ret"] * b["seed"] for b in valid_bots) / tot_s, 2) if tot_s else 0.0
    else:
        daily_ret = round(cum_ret / days, 2) if cum_ret is not None else None

    heatmap = {}
    for b in bots:
        for k, v in (b.get("hm_grid") or {}).items():
            heatmap[k] = round(heatmap.get(k, 0.0) + v, 4)

    dd_danger = [{"name": b["name"], "today_dd": b["today_dd"]}
                 for b in bots if b.get("today_dd") is not None and b["today_dd"] <= -10]
    dd_warn = [{"name": b["name"], "today_dd": b["today_dd"]}
               for b in bots if b.get("today_dd") is not None and -10 < b["today_dd"] <= -5]

    summary = {
        "assets": round(assets, 2),
        "cum_ret": cum_ret,
        "cum_delta": round(assets - seed, 2),
        "daily_ret": daily_ret,
        "days": round(days, 1),
        "alive": sum(1 for b in bots if b["alive"]),
        "count": len(bots),
        "with_positions": sum(1 for b in bots if b["holding"] is True),
        "no_positions": [b["name"] for b in bots if b["holding"] is False],
        "unknown_positions": [b["name"] for b in bots if b["holding"] is None],
        "stale": [b["name"] for b in bots
                  if b["age_min"] is not None and b["age_min"] > STALE_MIN],
        "heatmap": heatmap,
        "dd_danger": dd_danger,
        "dd_warn": dd_warn,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    return {"summary": summary, "bots": bots, "stale_min": STALE_MIN}


def collect():
    return collect_bots(BOTS)


def collect_excluded():
    return collect_bots(EXCLUDED_BOTS)


# ── 시간별 스냅샷 기록 (매시 :00·:30, 봇별 일평균수익률 누적) ──────────────
SNAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots.json")
SNAP_KEEP = 48          # 최근 48행(=30분×48=24시간) 보관
SNAP_LOCK = threading.Lock()


def load_snapshots():
    return safe_load_json(SNAP_PATH, [])


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
        atomic_save_json(SNAP_PATH, snaps)
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
    return safe_load_json(ASSET_PATH, [])


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
            atomic_save_json(ASSET_PATH, seed[-ASSET_KEEP:])


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
        atomic_save_json(ASSET_PATH, hist)


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
    """공개 OHLCV(API 키 불필요)로 BTC/USDT 종가 캔들. OKX/Bybit/Gate/Binance 교차 폴백 및 30초 캐시."""
    if tf not in BTC_TF_MS:
        tf = "1h"
    now = time.time()
    with _btc_lock:
        c = _btc_cache.get(tf)
        if c and now - c[0] < 30:
            return c[1]
    import ccxt
    candles = []
    # 바이낸스 IP ban/레이트리밋 대비 OKX -> Bybit -> Gate -> Binance 순으로 교차 조회
    for ex_cls in [ccxt.okx, ccxt.bybit, ccxt.gate, ccxt.binance]:
        try:
            client = ex_cls({"enableRateLimit": True, "timeout": 5000})
            raw = client.fetch_ohlcv("BTC/USDT", timeframe=tf, limit=limit)
            if raw:
                candles = [[r[0], r[4]] for r in raw]   # [ts_ms, 종가]
                break
        except Exception:
            continue

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

    if candles:
        for ts_ms, close in candles:
            cutoff = ts_ms + interval               # 캔들 종료시점 이하의 마지막 자산값(전방채움)
            idx = bisect.bisect_right(keys, cutoff) - 1
            asset = apts[idx][1] if idx >= 0 else None
            points.append({"t": ts_ms, "btc": close, "asset": asset})
    elif apts:
        # 거래소 캔들 전체 실패 시 자산 데이터(apts) 단독 포인트 폴백 (차트 막대 보장)
        step = max(1, len(apts) // 60)
        sample = apts[::step][-60:]
        for ts_ms, val in sample:
            points.append({"t": ts_ms, "btc": None, "asset": val})

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
        elif self.path == "/api/integrity_status":
            state_file = os.path.join(BASE, "data", "integrity_toggle.json")
            enabled = safe_load_json(state_file, {"enabled": True}).get("enabled", True)
            body = json.dumps({"enabled": enabled}).encode()
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

    def do_POST(self):
        if self.path == "/api/integrity_toggle":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                enabled = bool(data.get("enabled", True))
                
                state_file = os.path.join(BASE, "data", "integrity_toggle.json")
                atomic_save_json(state_file, {"enabled": enabled})
                
                body = json.dumps({"status": "ok", "enabled": enabled}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_error(400, f"Bad Request: {e}")
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        pass


_WATCH_FILES = ["app.py", "discord_alert.py"]
_FILE_MTIMES = {}

def _check_and_reload_if_modified():
    """소스 파일(app.py, discord_alert.py 등) 변경 시 프로세스를 자동 자가 재기동(os.execv)하여 메모리 구버전 잔존을 원천 차단"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for fname in _WATCH_FILES:
        fpath = os.path.join(base_dir, fname)
        if os.path.exists(fpath):
            try:
                mt = os.path.getmtime(fpath)
                if fname in _FILE_MTIMES:
                    if _FILE_MTIMES[fname] != mt:
                        print(f"[AUTO-RELOAD] {fname} 소스 변경 감지! (mtime: {_FILE_MTIMES[fname]} -> {mt}). 프로세스를 자동 재기동합니다...", flush=True)
                        os.execv(sys.executable, [sys.executable] + sys.argv)
                else:
                    _FILE_MTIMES[fname] = mt
            except Exception as e:
                pass


def discord_1min_loop():
    """기존 매 1분(60초) 간격 디스코드 실시간 관제 알림 스레드 (기존 깔끔한 2개 그룹 양식)."""
    import discord_alert
    import importlib
    time.sleep(30)   # 거래소 캐시(EX_CACHE) 워밍업 후 첫 발송
    loop_count = 0
    while True:
        t0 = time.time()
        try:
            _check_and_reload_if_modified()
            run_check_auto_mode_switch_all()
            importlib.reload(discord_alert)
            data = collect()
            t1 = time.time()
            ok, info = discord_alert.tick(data, tick_count=loop_count, include_bot_charts=False)
            t2 = time.time()
            loop_count += 1
            print(f"[DISCORD 1MIN] {time.strftime('%H:%M:%S')} ok={ok} {info} "
                  f"collect={t1-t0:.1f}s post={t2-t1:.1f}s", flush=True)
        except Exception as e:
            print(f"[DISCORD 1MIN] {time.strftime('%H:%M:%S')} 예외: {str(e)[:150]}", flush=True)
        time.sleep(max(1, 60 - (time.time() - t0)))


def discord_5min_loop():
    """매 5분 정각(00분00초, 05분00초, 10분00초...) 디스코드 8개 봇 개별 파동 알림 스레드 (봇별 개별 파동 차트 포함 양식)."""
    import discord_alert
    import importlib
    time.sleep(15)   # 첫 기동 시 캐시 워밍업 후 정각 대기
    loop_count = 0
    while True:
        now = time.time()
        dt = datetime.fromtimestamp(now)
        # 매 5분 정각 시각 계산 (00, 05, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55분 00초)
        min_mod = dt.minute % 5
        sec_diff = min_mod * 60 + dt.second + dt.microsecond / 1e6
        if sec_diff < 0.5:
            target_time = now
        else:
            target_time = now + (300 - sec_diff)
            
        sleep_sec = target_time - time.time()
        if sleep_sec > 0:
            time.sleep(sleep_sec)

        t0 = time.time()
        try:
            _check_and_reload_if_modified()
            importlib.reload(discord_alert)
            data = collect()
            t1 = time.time()
            ok, info = discord_alert.tick(data, tick_count=loop_count, include_bot_charts=True)
            t2 = time.time()
            loop_count += 1
            print(f"[DISCORD 5MIN] {time.strftime('%H:%M:%S')} ok={ok} {info} "
                  f"collect={t1-t0:.1f}s post={t2-t1:.1f}s", flush=True)
        except Exception as e:
            print(f"[DISCORD 5MIN] {time.strftime('%H:%M:%S')} 예외: {str(e)[:150]}", flush=True)
        
        # 중복 발송 방지를 위해 최소 10초 대기 후 다음 5분 정각 대기 루프 진입
        time.sleep(10)


def auto_repair_bot(folder):
    """단일 봇 data/trade_history.csv 진입유실 및 수수료 공란/0원 점검 및 자동 보정/채우기"""
    import pandas as pd
    base = os.path.join(BASE, folder)
    csv_path = os.path.join(base, "data", "trade_history.csv")
    if not os.path.exists(csv_path):
        return 0
    try:
        sys.modules.pop("core.history_helper", None)
        sys.modules.pop("core", None)
        sys.path.insert(0, base)
        from core.history_helper import aggregate_and_pair_trades, load_local_trade_history
        raw = load_local_trade_history()
        paired = aggregate_and_pair_trades(raw)
        missing = [p for p in paired if not p.get("entry_time") or str(p.get("entry_time")).strip() in ("", "—", "None") or "진입유실" in str(p.get("status"))]

        df = pd.read_csv(csv_path)
        if "수수료(USDT)" not in df.columns:
            df["수수료(USDT)"] = 0.0

        # [수수료 공란/0원 자동 채우기]
        fee_repaired = 0
        for idx_row in df.index:
            try:
                px = float(df.at[idx_row, "가격"] or 0)
                amt = float(df.at[idx_row, "수량"] or 0)
                fee_v = df.at[idx_row, "수수료(USDT)"]
                if (pd.isna(fee_v) or str(fee_v).strip() in ("", "0", "0.0", "None")) and px > 0 and amt > 0:
                    df.at[idx_row, "수수료(USDT)"] = round(px * amt * 0.0005, 8)
                    fee_repaired += 1
            except Exception:
                pass

        # [가상 10초 전 진입행 강제 생성 금지] 실측되지 않은 ID_AUTO_FIX_ 진입행 삽입 차단
        if fee_repaired > 0:
            final_df = df
            final_df = final_df.drop_duplicates()
            final_df["dt"] = pd.to_datetime(final_df["시간"], errors="coerce")
            final_df = final_df.sort_values(by="dt", ascending=True).drop(columns=["dt"])
            final_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            print(f"[AUTO_REPAIR] {folder}: 진입유실 {added}건, 수수료 공란 {fee_repaired}건 자동 복구 저장 완료", flush=True)
        return added + fee_repaired
    except Exception as e:
        print(f"[AUTO_REPAIR] {folder} 점검 중 예외: {e}", flush=True)
        return 0
    finally:
        if sys.path[0] == base:
            sys.path.pop(0)


def auto_repair_all_bots():
    """전체 8개 봇의 매매이력 CSV 진입유실 점검 및 자동 보정 (봇별 복구 결과 리턴)"""
    res = {}
    tot = 0
    for folder, _port, _ex in BOTS:
        cnt = auto_repair_bot(folder)
        if cnt > 0:
            res[folder] = cnt
            tot += cnt
    return tot, res


def auto_repair_loop():
    """매 5분(300초) 주기 백그라운드 8개 봇 매매이력 자동 점검 및 디스코드 알림 스레드"""
    time.sleep(10)  # 앱 초기화 후 10초 대기
    while True:
        try:
            t0 = time.time()
            cnt, details = auto_repair_all_bots()
            if cnt > 0:
                detail_str = ", ".join([f"{k}: {v}건" for k, v in details.items()])
                log_msg = f"[AUTO_REPAIR] {time.strftime('%H:%M:%S')} 전체 봇 점검 완료: 총 {cnt}건 진입유실 자동 채우기 완료 ({detail_str}) ({time.time()-t0:.2f}초)"
                print(log_msg, flush=True)

                # 디스코드 알림 발송
                try:
                    import discord_alert
                    alert_msg = (
                        f"🛠️ **[8888 스마트 힐링] 매매이력 진입유실 자동 복구 완료!**\n"
                        f"• **총 복구 건수**: **{cnt}건** ({detail_str})\n"
                        f"• `trade_history.csv` 진입시각 및 실현손익 정합성 100% 자동 채우기 완료!"
                    )
                    discord_alert._post(alert_msg)
                except Exception as _e:
                    print(f"[AUTO_REPAIR] 디스코드 알림 발송 중 예외: {_e}", flush=True)
        except Exception as e:
            print(f"[AUTO_REPAIR] {time.strftime('%H:%M:%S')} 스레드 예외: {e}", flush=True)
        time.sleep(300)


def discord_listener_loop():
    """디스코드 양방향 원격 제어 봇 웹소켓 리스너 스레드"""
    try:
        import discord_bot_listener
        asyncio.run(discord_bot_listener.run_gateway_listener())
    except Exception as e:
        print(f"[DISCORD_LISTENER] 스레드 예외: {e}", flush=True)


def run_check_auto_mode_switch_all():
    """전체 8개 봇 실시간 매매방향 자동 스위칭(최근 5전 중 2패 이상 시 대칭 반전) 격리 프로세스 실행 함수"""
    import subprocess
    target_bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
    for b in target_bots:
        bot_path = os.path.join(os.path.dirname(BASE), str(b))
        if os.path.exists(f"{bot_path}/core/engine.py"):
            try:
                cmd = [sys.executable, "-c", "import core.engine; e=core.engine.QuantumEngine(); e.check_auto_mode_switch()"]
                subprocess.run(cmd, cwd=bot_path, capture_output=True, timeout=10)
            except Exception as e:
                print(f"[AUTO_SWITCH_GUARD] {b} 스위처 실행 예외: {e}", flush=True)


def auto_mode_switch_guard_loop():
    """전체 8개 봇 적응형 자동 스위처 2중 중앙 관제 루프 (30초 정속 실시간 감시)"""
    time.sleep(10)
    while True:
        try:
            run_check_auto_mode_switch_all()
        except Exception as e:
            print(f"[AUTO_SWITCH_GUARD] 스레드 예외: {e}", flush=True)
        time.sleep(30)



import hashlib
import shutil

def get_file_hash(path):
    if not os.path.exists(path):
        return None
    hasher = hashlib.sha256()
    with open(path, 'rb') as f:
        hasher.update(f.read().replace(b"\r\n", b"\n"))
    return hasher.hexdigest()

def checksum_guard_loop():
    """8개 봇의 핵심 로직 파일 변조 감시 및 자동 롤백 스레드"""
    time.sleep(10)
    target_bots = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]
    target_files = ["bot.py", "core/strategy.py", "core/trader.py", "core/engine.py", "config.json"]
    
    while True:
        try:
            # 토글 상태 확인
            state_file = os.path.join(BASE, "data", "integrity_toggle.json")
            is_enabled = safe_load_json(state_file, {"enabled": True}).get("enabled", True)
            if not is_enabled:
                time.sleep(60)
                continue
                
            for b in target_bots:
                bot_path = os.path.join(os.path.dirname(BASE), str(b))
                golden_dir = f"{bot_path}/.golden"
                if not os.path.exists(golden_dir):
                    continue
                
                for tf in target_files:
                    golden_file = f"{golden_dir}/{tf}"
                    live_file = f"{bot_path}/{tf}"
                    
                    golden_hash = get_file_hash(golden_file)
                    if not golden_hash:
                        continue
                        
                    live_hash = get_file_hash(live_file)
                    
                    if golden_hash != live_hash:
                        # 롤백 수행
                        try:
                            shutil.copy2(golden_file, live_file)
                            alert_msg = f"🚨 **[{b}] 로직 오염 감지!**\n`{tf}` 파일이 변조되었습니다.\n즉시 Golden Backup(원본)으로 롤백 복구를 완료했습니다."
                            print(f"[CHECKSUM_GUARD] {alert_msg}", flush=True)
                            try:
                                import discord_alert
                                discord_alert._post(alert_msg)
                            except:
                                pass
                        except Exception as e:
                            print(f"[CHECKSUM_GUARD] 롤백 실패: {e}")
        except Exception as e:
            print(f"[CHECKSUM_GUARD] 스레드 예외: {e}", flush=True)
            
        time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=checksum_guard_loop, daemon=True).start()  # 파일 변조 감시 및 자동 롤백 스레드

    threading.Thread(target=exchange_loop, daemon=True).start()
    threading.Thread(target=snapshot_loop, daemon=True).start()
    threading.Thread(target=asset_loop, daemon=True).start()   # [B안] 총자산 1분 기록
    threading.Thread(target=discord_1min_loop, daemon=True).start()   # 매 1분 디스코드 2개 그룹(그룹 1, 그룹 2) 실시간 관제 알림 스레드
    threading.Thread(target=auto_repair_loop, daemon=True).start()  # 매 5분 매매이력 자동 점검 스레드
    threading.Thread(target=discord_listener_loop, daemon=True).start()  # 디스코드 양방향 원격 제어 봇 스레드
    threading.Thread(target=auto_mode_switch_guard_loop, daemon=True).start()  # 8403,5,7,9 2중 자동 스위칭 중앙 관제 스레드
    print(f"8888 통합 관제 대시보드: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
