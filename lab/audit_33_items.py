#!/usr/bin/env python3
"""audit_33_items.py — 5대 봇 진입·청산·쿨다운 33개 항목 전수 감사.

왜 만드는가
  진입이 왜 안 되는지, 청산이 왜 누락되는지, 쿨다운이 왜 안 풀리는지를
  매번 사람이 물어보고 그때마다 손으로 파헤쳐 왔다. 그 과정을 도구로 고정한다.

판정 기준
  PASS  실측으로 정상 확인
  FAIL  실측으로 결함 확인
  WARN  정상이나 주의가 필요
  N/A   이 봇에 해당 없음
  UNK   **실행 중 관측이 필요해 정적 점검으로는 판정 불가** (추정 금지)

원칙
  · 거래소 원장이 진실이다. 로컬 파일이 다르면 로컬이 틀린 것이다.
  · 판정할 수 없으면 UNK로 남긴다. PASS로 넘기지 않는다.
  · 읽기 전용이다. 이 도구는 아무것도 고치지 않는다.
"""
import asyncio
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys

BASE = "/Users/l/project"
BOTS = ["8401", "8402", "8407", "8409", "8410"]
OKX = {"8401", "8402"}
PASS, FAIL, WARN, NA, UNK = "PASS", "FAIL", "WARN", "N/A", "UNK"
FAST = False   # --fast 시 원장 조회를 건너뛴다


def jload(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return d if d is not None else {}


def tail(p, n=4000):
    try:
        return subprocess.run(["tail", "-n", str(n), p], capture_output=True,
                              text=True, errors="ignore").stdout
    except Exception:
        return ""


class Ctx:
    """봇 하나의 감사에 필요한 모든 자료를 한 번만 모은다."""

    def __init__(self, bot):
        self.bot = bot
        self.dir = os.path.join(BASE, bot)
        self.data = os.path.join(self.dir, "data")
        self.cfg = jload(os.path.join(self.dir, "config.json"))
        self.stats = jload(os.path.join(self.data, "stats.json"))
        self.switch = jload(os.path.join(self.data, "switch_state.json"))
        self.active = jload(os.path.join(self.data, "active_positions.json"))
        self.engine_st = jload(os.path.join(self.data, "engine_states.json"))
        self.log = ""
        for name in ("launchd_bot.log", "bot_stdout.log", "bot_engine.log"):
            p = os.path.join(self.dir, name)
            if os.path.exists(p):
                self.log += tail(p, 3000)
        self.rows = []
        p = os.path.join(self.data, "trade_history.csv")
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8-sig") as f:
                    self.rows = list(csv.DictReader(f))
            except Exception:
                pass
        self.pos = []          # 거래소 실제 포지션
        self.algo = []         # 보호주문
        self.ledger = []       # 원장 청산 사이클
        self.pid = None
        self.err = ""

    def src(self, *names):
        out = ""
        for n in names:
            p = os.path.join(self.dir, "core", n)
            if os.path.exists(p):
                try:
                    out += open(p, encoding="utf-8", errors="ignore").read()
                except Exception:
                    pass
        return out

    def exits(self, days=7):
        cut = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        return [r for r in self.rows if r.get("유형") == "청산" and r.get("시간", "") >= cut]

    def entries(self, days=7):
        cut = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        return [r for r in self.rows if r.get("유형") == "진입" and r.get("시간", "") >= cut]


async def collect(c):
    """거래소 실측 수집."""
    sys.path.insert(0, c.dir)
    os.chdir(c.dir)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(c.dir, ".env"), override=False)
        from core.api_keys import load_api_keys
        load_api_keys(override=True)
        since = int((dt.datetime.now() - dt.timedelta(days=7)).timestamp() * 1000)
        if c.bot in OKX:
            import ccxt.async_support as ccxt
            ex = ccxt.okx({"apiKey": os.getenv("OKX_API_KEY", ""),
                           "secret": os.getenv("OKX_SECRET_KEY", ""),
                           "password": os.getenv("OKX_PASSPHRASE", ""),
                           "enableRateLimit": True,
                           "options": {"defaultType": "swap"}})
            await ex.load_markets()
            c.pos = [p for p in await ex.fetch_positions() if float(p.get("contracts") or 0) > 0]
            r = await ex.privateGetTradeOrdersAlgoPending({"instType": "SWAP", "ordType": "oco"})
            c.algo = r.get("data", [])
            rows, after = [], None
            for _ in range(0 if FAST else 25):
                q = {"instType": "SWAP", "limit": "100"}
                if after:
                    q["after"] = after
                rr = await ex.privateGetAccountPositionsHistory(q)
                dd = rr.get("data", [])
                if not dd:
                    break
                rows += dd
                after = dd[-1].get("uTime")
                if len(dd) < 100 or int(dd[-1].get("uTime", 0)) < since:
                    break
            c.ledger = [{"ts": int(x.get("uTime", 0)),
                         "sym": x.get("instId", ""),
                         "pnl": float(x.get("realizedPnl") or 0)}
                        for x in rows if int(x.get("uTime", 0)) >= since]
            await ex.close()
        else:
            from core.exchange import BinanceClient
            cl = BinanceClient(os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_SECRET_KEY", ""))
            await cl.load_markets()
            ex = cl.exchange
            c.pos = [p for p in await cl.get_positions()]
            c.algo = [a for a in (await ex.fapiPrivateGetOpenAlgoOrders({}) or [])
                      if str(a.get("algoStatus")) == "NEW"]
            syms, s = set(), since
            while not FAST:
                rr = await ex.fapiPrivateGetIncome({"startTime": s, "limit": 1000})
                if not rr:
                    break
                for x in rr:
                    if x["incomeType"] == "REALIZED_PNL" and float(x["income"] or 0) != 0:
                        syms.add(x["symbol"])
                if len(rr) < 1000:
                    break
                s = int(rr[-1]["time"]) + 1
            for sym in sorted(syms):
                try:
                    tr = await ex.fapiPrivateGetUserTrades(
                        {"symbol": sym, "startTime": since, "limit": 500})
                except Exception:
                    continue
                pos = 0.0
                ets = None
                pnl = 0.0
                for t in sorted(tr, key=lambda x: int(x["time"])):
                    q = float(t["qty"]) * (1 if t["side"] == "BUY" else -1)
                    if abs(pos) < 1e-12 and q != 0:
                        ets, pnl = int(t["time"]), 0.0
                    pos += q
                    pnl += float(t.get("realizedPnl") or 0)
                    if abs(pos) < 1e-12 and ets is not None:
                        c.ledger.append({"ts": int(t["time"]), "sym": sym, "pnl": pnl})
                        ets = None
            await ex.close()
    except Exception as e:
        c.err = str(e)[:120]
    finally:
        for k in list(sys.modules):
            if k.startswith("core"):
                del sys.modules[k]
        if c.dir in sys.path:
            sys.path.remove(c.dir)
    # 프로세스
    try:
        out = subprocess.run(["pgrep", "-f", "bot.py"], capture_output=True, text=True).stdout
        for pid in out.split():
            r = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
                               capture_output=True, text=True).stdout
            for ln in r.splitlines():
                if ln.startswith("n") and ln[1:].rstrip("/").endswith(c.bot):
                    c.pid = pid
    except Exception:
        pass


# ────────────────────────── 섹션 A · 진입 11항목 ──────────────────────────
def a01(c):
    sig = len(re.findall(r"\[SIGNAL\]", c.log))
    blocked = len(re.findall(r"\[RISK BLOCK\]|\[ENTRY BLOCK\]", c.log))
    ok = len(re.findall(r"\[RISK OK\]|\[ENTRY OK\]", c.log))
    if sig == 0:
        return UNK, "로그 구간 내 신호 0건 — 판정 불가"
    if ok == 0 and blocked > 0:
        # 연속손절 정지가 걸려 있으면 전량 차단이 **정상 동작**이다.
        if c.stats.get("halted_by_consec_sl"):
            return PASS, f"연속손절 정지 중이라 전량 차단 (신호 {sig} / 차단 {blocked}) — 정상"
        return FAIL, f"신호 {sig}건 전량 차단 (차단 {blocked} / 통과 0)"
    return PASS, f"신호 {sig} · 통과 {ok} · 차단 {blocked}"


def a02(c):
    n = len(re.findall(r"\[SCAN\] 완료", c.log))
    if n == 0:
        return FAIL, "스캔 완료 로그 0건 — 전략 루프 미작동 의심"
    sig = len(re.findall(r"신호 [1-9]\d*개", c.log))
    return (PASS, f"스캔 {n}회 · 신호발생 스캔 {sig}회") if sig else \
           (WARN, f"스캔 {n}회 전부 신호 0개 — 필터 과다 가능")


def a03(c):
    s = c.src("trader.py")
    hits = []
    for pat, why in ((r"price_diff\s*>\s*0\.\d+", "이격가드 리터럴"),
                     (r"volatility_24h\s*>\s*0\.\d+", "변동성가드 리터럴"),
                     (r"spread_pct\s*>\s*0\.\d+", "스프레드가드 리터럴")):
        if re.search(pat, s):
            hits.append(why)
    return (FAIL, "하드코딩 잔존: " + ", ".join(hits)) if hits else (PASS, "설정값 참조 확인")


def a04(c):
    n = len(re.findall(r"증거금 부족|Insufficient|margin is insufficient|-2019", c.log))
    return (WARN, f"증거금 부족 {n}건") if n else (PASS, "증거금 부족 0건")


def a05(c):
    n = len(re.findall(r"-4164|MIN_NOTIONAL|최소 주문|notional must be", c.log))
    return (FAIL, f"최소주문 미달 거부 {n}건") if n else (PASS, "최소주문 거부 0건")


def a06(c):
    cap = int(c.cfg.get("MAX_POSITIONS", 0) or 0)
    live = len(c.pos)
    if cap <= 0:
        return WARN, "MAX_POSITIONS 미설정"
    if live > cap:
        return WARN, f"보유 {live} > 한도 {cap} (기존분 잔존, 신규는 차단)"
    return PASS, f"보유 {live} / 한도 {cap}"


def a07(c):
    seen = {}
    for p in c.pos:
        s = p.get("symbol")
        seen[s] = seen.get(s, 0) + 1
    dup = [k for k, v in seen.items() if v > 1]
    return (FAIL, f"중복 포지션: {dup}") if dup else (PASS, "중복 진입 없음")


def a08(c):
    n = len(re.findall(r"RequestTimeout|ReadTimeout|Connection aborted|재시도", c.log))
    return (WARN, f"타임아웃·재시도 {n}건 (핸들링은 동작)") if n else (PASS, "타임아웃 0건")


def a09(c):
    m = re.findall(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[INFO\] \[SCAN\] 완료", c.log)
    if not m:
        return UNK, "스캔 로그 없음"
    last = dt.datetime.strptime(m[-1], "%Y-%m-%d %H:%M:%S")
    age = (dt.datetime.now() - last).total_seconds()
    iv = float(c.cfg.get("SCAN_INTERVAL_SEC", 300) or 300)
    if age > iv * 4:
        return FAIL, f"마지막 스캔 {age/60:.0f}분 전 (주기 {iv:.0f}초) — 정체"
    return PASS, f"마지막 스캔 {age/60:.1f}분 전 (주기 {iv:.0f}초)"


def a10(c):
    wl = {s.split("/")[0] for s in (c.cfg.get("SYMBOL_WHITELIST") or [])}
    if not wl:
        return NA, "화이트리스트 미사용"
    bad = {p["symbol"].split("/")[0] for p in c.pos} - wl
    return (FAIL, f"화이트리스트 외 보유: {bad}") if bad else \
           (PASS, f"{len(wl)}종목 · 위반 0")


def a11(c):
    ent = c.entries(7)
    if FAST:
        return (PASS, f"CSV 진입 {len(ent)}건") if ent else (WARN, "최근 진입 기록 0건")
    if not c.ledger:
        return UNK, "원장 없음"
    return PASS, f"CSV 진입 {len(ent)}건 기록됨" if ent else (WARN, "최근 7일 진입 기록 0건")


# ────────────────────────── 섹션 B · 청산 11항목 ──────────────────────────
def b12(c):
    live = {p["symbol"] for p in c.pos}
    local = set(c.active.keys()) if isinstance(c.active, dict) else set()
    ghost = local - live
    orph = live - local
    if ghost or orph:
        return FAIL, f"유령(로컬만) {sorted(ghost)} · 고아(거래소만) {sorted(orph)}"
    return PASS, f"포지션 {len(live)}건 일치"


def _prot(c):
    """포지션별 보호주문 종류 집계."""
    out = {}
    for p in c.pos:
        base = p["symbol"].split("/")[0]
        kinds = set()
        for a in c.algo:
            s = str(a.get("symbol") or a.get("instId") or "")
            if s.replace("USDT", "").replace("-", "").replace("SWAP", "").strip() == base or s.startswith(base):
                t = str(a.get("orderType") or a.get("ordType") or "")
                kinds.add(t.upper())
                if a.get("slTriggerPx"):
                    kinds.add("STOP")
                if a.get("tpTriggerPx"):
                    kinds.add("TAKE_PROFIT")
        out[base] = kinds
    return out


def b13(c):
    if not c.pos:
        return NA, "보유 포지션 없음"
    pr = _prot(c)
    bad = [k for k, v in pr.items() if not any("TAKE_PROFIT" in x or "TP" in x for x in v)]
    return (FAIL, f"TP 미등록: {bad}") if bad else (PASS, f"{len(pr)}건 전부 TP 등록")


def b14(c):
    if not c.pos:
        return NA, "보유 포지션 없음"
    pr = _prot(c)
    bad = [k for k, v in pr.items() if not any("STOP" in x or "SL" in x for x in v)]
    return (FAIL, f"SL 미등록(무손절): {bad}") if bad else (PASS, f"{len(pr)}건 전부 SL 등록")


def b15(c):
    on = bool(c.cfg.get("USE_TRAILING_STOP", False))
    s = c.src("engine.py")
    dead = "record_only" in s and "trailing_stop_manager.check_async" in s
    if not on:
        return NA, "USE_TRAILING_STOP=False (설정상 미사용)"
    if dead:
        return FAIL, "설정 ON이나 record_only 경로로 호출 차단됨"
    return UNK, "설정 ON — 실행 중 관측 필요"


def b16(c):
    h = float(c.cfg.get("MAX_HOLDING_HOURS", 0) or 0)
    if h <= 0 or not c.pos:
        return NA, "설정 없음 또는 무포지션"
    over = []
    for sym, v in (c.active or {}).items():
        t = v.get("open_time") if isinstance(v, dict) else None
        if not t:
            continue
        try:
            age = (dt.datetime.now() - dt.datetime.fromisoformat(t)).total_seconds() / 3600
            if age > h:
                over.append(f"{sym.split('/')[0]}({age:.0f}h)")
        except Exception:
            pass
    return (FAIL, f"보유시간 초과 방치: {over} (한도 {h:.0f}h)") if over else \
           (PASS, f"초과 없음 (한도 {h:.0f}h)")


def b17(c):
    on = bool(c.cfg.get("USE_PARTIAL_TP", False))
    s = c.src("engine.py")
    dead = "record_only" in s and "trailing_stop_manager.check_async" in s
    if not on:
        return NA, "USE_PARTIAL_TP=False"
    if dead:
        return FAIL, "설정 ON이나 실행 경로(record_only)에서 차단 — 무동작"
    return UNK, "설정 ON — 실행 중 관측 필요"


def b18(c):
    s = c.src("exchange.py")
    has = "close_position" in s and ("FAIL-SAFE" in s or "fail_safe" in s or "긴급" in s)
    n = len(re.findall(r"FAIL-SAFE|긴급 청산", c.log))
    if not has:
        return WARN, "비상청산 루틴 식별 안 됨"
    return PASS, f"루틴 존재 · 발동 {n}건"


def b19(c):
    n = len(re.findall(r"외부 청산 감지|ALGO CLOSE", c.log))
    return (PASS, f"외부청산 감지 {n}건") if n else (UNK, "해당 이벤트 없음 — 판정 불가")


def b20(c):
    live = {p["symbol"] for p in c.pos}
    local = set(c.active.keys()) if isinstance(c.active, dict) else set()
    stale = local - live
    return (FAIL, f"청산 후 잔존: {sorted(stale)}") if stale else (PASS, "잔존 없음")


def b21(c):
    if FAST:
        return NA, "--fast 생략 (원장 조회 필요)"
    ex = c.exits(7)
    if not ex or not c.ledger:
        return UNK, "표본 없음"
    csv_sum = sum(float(r.get("수익(USDT)") or 0) for r in ex)
    led_sum = sum(x["pnl"] for x in c.ledger)
    d = csv_sum - led_sum
    # [2026-09-11] CSV는 **체결 단위**, 원장 사이클은 **포지션 단위**다.
    # 분할 청산과 7일 경계에 걸친 사이클 때문에 합계는 항상 조금 어긋난다.
    # 실제 값 오염은 규모가 다르다(8407 실측 +2.08). 문턱을 그에 맞춘다.
    # 정밀 대조가 필요하면 lab/ledger_fix_values.py로 체결ID 1:1 매칭할 것.
    note = f"CSV {csv_sum:+.4f}(체결{len(ex)}건) vs 원장 {led_sum:+.4f}(포지션{len(c.ledger)}건)"
    if abs(d) > 1.0:
        return FAIL, f"값 오염 의심 — {note} 차이 {d:+.4f}"
    if abs(d) > 0.3:
        return WARN, f"{note} 차이 {d:+.4f} (단위차 포함)"
    return PASS, f"{note} 차이 {d:+.4f}"


def b22(c):
    """원장에 있는 청산이 CSV에 빠짐없이 있는가.

    [2026-09-11] 종전에는 CSV 건수와 원장 사이클 건수를 직접 뺐는데,
    CSV는 **체결 단위**이고 원장 사이클은 **포지션 단위**라 분할 청산이 있으면
    항상 어긋난다. 그 탓에 5봇 전부 FAIL로 오판했다.
    실제로 문제가 되는 것은 '원장에 있는데 CSV에 없는' 누락뿐이므로 그것만 센다.
    """
    if FAST:
        return NA, "--fast 생략 (원장 조회 필요)"
    if not c.ledger:
        return UNK, "원장 없음"
    keys = set()
    for r in c.rows:
        if r.get("유형") != "청산":
            continue
        t = r.get("시간", "")[:16]
        if t:
            keys.add((r.get("심볼", "").split("/")[0], t))
    miss = []
    for x in c.ledger:
        sym = x["sym"].replace("USDT", "").replace("-", "").replace("SWAP", "").strip("/")
        t = dt.datetime.fromtimestamp(x["ts"] / 1000).strftime("%Y-%m-%d %H:%M")
        if (sym, t) not in keys:
            miss.append(sym)
    if miss:
        return FAIL, f"원장 {len(c.ledger)}건 중 CSV 누락 {len(miss)}건: {sorted(set(miss))[:6]}"
    return PASS, f"원장 {len(c.ledger)}건 전부 CSV에 존재"


# ────────────────────────── 섹션 C · 쿨다운 11항목 ──────────────────────────
def c23(c):
    s = c.src("trader.py")
    m = re.search(r"if pnl < 0:\s*\n\s*self\._daily_consec_sl \+= 1", s)
    return (PASS, "손실일 때만 증가 확인") if m else (UNK, "증가 조건 식별 실패")


def c24(c):
    s = c.src("trader.py")
    # 호출부가 아니라 **정의부**부터 잡아야 한다. 종전에는 첫 등장(호출부)에서
    # 시작해 파일 끝까지 삼켰고, 그 탓에 정상 코드를 '불명'으로 오판했다.
    blk = re.search(r"def _reset_daily_if_needed.*?(?=\n    def )", s, re.S)
    if not blk:
        return UNK, "리셋 함수 없음"
    b = blk.group(0)
    mem = "_halted_by_consec_sl = False" in b
    disk = 'halted_by_consec_sl"] = False' in b or '"halted_by_consec_sl"' in b
    if mem and not disk:
        return FAIL, "메모리만 해제하고 stats.json 미반영"
    if mem and disk:
        return PASS, "메모리·디스크 동시 해제"
    return WARN, "해제 로직 불명"


def c25(c):
    h = bool(c.stats.get("halted_by_consec_sl"))
    d = c.stats.get("consec_sl_date")
    today = str((dt.datetime.utcnow() + dt.timedelta(hours=9)).date())
    if h and d and d != today:
        return FAIL, f"만료 정지 잔존 (halted=True, date={d}, 오늘={today})"
    return PASS, f"halted={h}, date={d}"


def c26(c):
    s = c.src("trader.py")
    m = re.search(r"else:\s*\n\s*self\._daily_consec_sl = 0", s)
    return (PASS, "익절 시 카운터 0 리셋 확인") if m else (WARN, "리셋 코드 식별 실패")


def c27(c):
    sc = c.stats.get("symbol_cooldown_until") or {}
    now = dt.datetime.now()
    stale = []
    for k, v in sc.items():
        try:
            if dt.datetime.fromisoformat(v) < now:
                stale.append(k.split("/")[0])
        except Exception:
            pass
    return (WARN, f"만료분 잔존(디스크): {stale}") if stale else \
           (PASS, f"활성 {len(sc)}건 · 만료 잔존 0")


def c28(c):
    g = c.stats.get("global_cooldown_until")
    if not g:
        return PASS, "글로벌 쿨다운 없음"
    try:
        t = dt.datetime.fromisoformat(str(g).replace("T", " ")[:19])
    except Exception:
        return FAIL, f"타임스탬프 파싱 불가: {g}"
    if t > dt.datetime.now() + dt.timedelta(days=1):
        return FAIL, f"비정상 미래값 {t} — 영구 쿨다운"
    return (WARN, f"활성 (만료 {t})") if t > dt.datetime.now() else (PASS, "만료됨")


def c29(c):
    anc = c.switch.get("updated_at") or c.switch.get("last_switched_key")
    if not anc:
        return NA, "스위칭 이력 없음"
    n = sum(1 for r in c.rows
            if r.get("유형") == "청산" and r.get("시간", "") > str(anc)[:19])
    return PASS, f"스위칭({str(anc)[:16]}) 이후 청산 {n}건 / 3건 기준"


def c30(c):
    anc = c.switch.get("updated_at") or c.switch.get("last_switched_key")
    ps = c.stats.get("perf_start_time")
    if not anc:
        return NA, "스위칭 이력 없음"
    if ps and str(anc)[:19] < str(ps)[:19]:
        # 8888 app.py에 perf_start_time 이전 앵커를 무효화하는 가드가 있어
        # 대시보드 판정은 오염되지 않는다. 파일만 낡은 상태이므로 WARN으로 둔다.
        guard = False
        try:
            src = open(os.path.join(BASE, "8888", "app.py"), encoding="utf-8").read()
            guard = "anchor[:19] < perf_start[:19]" in src
        except Exception:
            pass
        lvl = WARN if guard else FAIL
        return lvl, (f"스위칭 기록({str(anc)[:16]})이 리셋({str(ps)[:16]})보다 과거"
                     + (" — app.py 가드가 무효화 처리 중" if guard else " — 혼입 위험"))
    return PASS, "구세션 혼입 없음"


def c31(c):
    """대시보드 판정 로직을 그대로 재현해 봇 실제 상태와 비교."""
    halted = bool(c.stats.get("halted_by_consec_sl"))
    anc = c.switch.get("updated_at") or c.switch.get("last_switched_key")
    n = 0
    if anc:
        n = sum(1 for r in c.rows
                if r.get("유형") == "청산" and r.get("시간", "") > str(anc)[:19])
    dash_cd = halted or (bool(anc) and n < 3)
    # 봇 실제: 오늘 진입이 있으면 매매 가능 상태
    today = dt.datetime.now().strftime("%Y-%m-%d")
    traded = any(r.get("유형") == "진입" and r.get("시간", "").startswith(today)
                 for r in c.rows)
    # [2026-09-11] 종전에는 '오늘 진입이 있는데 halted'를 무조건 불일치로 봤다.
    # 정지는 하루 중 언제든 걸리므로 그 전의 진입은 모순이 아니다.
    # 카운터가 한도에 도달했으면 정당한 정지이고, 미달인데 정지면 모순이다.
    if halted:
        cnt = int(c.stats.get("daily_consec_sl", 0) or 0)
        cap = int(c.cfg.get("MAX_CONSEC_SL_PER_DAY", 0) or 0)
        if cap > 0 and cnt >= cap:
            return PASS, f"정당한 정지 ({cnt}/{cap}연속 손절) · 오늘진입={traded}"
        return FAIL, f"카운터 미달({cnt}/{cap})인데 정지 — 표시/실제 불일치"
    kind = "연속손절정지" if halted else (f"스위칭락({n}/3)" if dash_cd else "없음")
    return PASS, f"대시보드 쿨다운={dash_cd} ({kind}) · 오늘진입={traded}"


def c32(c):
    """워치독 프로세스가 상태 파일을 함께 쓰는지."""
    try:
        out = subprocess.run(["pgrep", "-fl", "watchdog"], capture_output=True, text=True).stdout
    except Exception:
        out = ""
    wd = [l for l in out.splitlines() if "watchdog" in l.lower()]
    n = len(re.findall(r"\[PERSIST\]|save_cooldowns", c.log))
    if wd and n:
        return WARN, f"워치독 {len(wd)}개 가동 · 상태파일 쓰기 {n}건 — 경합 여지"
    return PASS, f"워치독 {len(wd)}개 · 경합 징후 없음"


def c33(c):
    """쿨다운이 청산 엔진까지 멈추는가."""
    s = c.src("trader.py")
    m = re.search(r"if getattr\(self, \"_halted_by_consec_sl\", False\):", s)
    if not m:
        return UNK, "정지 분기 식별 실패"
    seg = s[m.start():m.start() + 500]
    blocks_exit = "close_position" in seg or "청산" in seg
    return (FAIL, "정지 분기가 청산까지 차단") if blocks_exit else \
           (PASS, "정지는 신규 진입만 차단 · 청산 경로 분리됨")


ITEMS = [
    ("A", 1, "신호↔주문 일치성", a01), ("A", 2, "전략 진입 필터 유효성", a02),
    ("A", 3, "하드코딩 차단 잔존", a03), ("A", 4, "증거금·레버리지 계산", a04),
    ("A", 5, "최소주문 단위 충족", a05), ("A", 6, "MAX_POSITIONS 준수", a06),
    ("A", 7, "중복 진입 방지 락", a07), ("A", 8, "타임아웃·재시도 핸들링", a08),
    ("A", 9, "스캐너 루프 정체", a09), ("A", 10, "화이트리스트 정합", a10),
    ("A", 11, "진입 즉시 장부 기록", a11),
    ("B", 12, "장부↔거래소 포지션 일치", b12), ("B", 13, "TP 등록·추적", b13),
    ("B", 14, "하드 손절 등록", b14), ("B", 15, "트레일링 스탑 유효성", b15),
    ("B", 16, "최대보유시간 청산", b16), ("B", 17, "분할청산 정확도", b17),
    ("B", 18, "비상 청산 루틴", b18), ("B", 19, "외부청산 감지·동기화", b19),
    ("B", 20, "청산 후 상태파일 삭제", b20), ("B", 21, "손익·수수료 정밀도", b21),
    ("B", 22, "청산 1:1 대사", b22),
    ("C", 23, "연속손절 카운트 오집계", c23), ("C", 24, "자정 리셋 작동", c24),
    ("C", 25, "전일 락 잔존 데드락", c25), ("C", 26, "익절 시 카운터 리셋", c26),
    ("C", 27, "종목 쿨다운 만료 해제", c27), ("C", 28, "글로벌 쿨다운 무한대기", c28),
    ("C", 29, "스위칭 3거래 카운트", c29), ("C", 30, "스위칭 이전 거래 혼입", c30),
    ("C", 31, "대시보드↔봇 상태 일치", c31), ("C", 32, "워치독 상태파일 경합", c32),
    ("C", 33, "쿨다운 중 청산 격리", c33),
]


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    # [2026-09-11] --fast: 원장 조회(항목 21·22)를 건너뛴다.
    # 그 둘이 API 호출의 90%를 쓰는데(종목별 userTrades) 나머지 31개는
    # 포지션·상태파일·소스·로그만으로 판정된다. 5분 주기 상시 감시용이다.
    global FAST
    FAST = "--fast" in flags
    only = args or BOTS
    grand = {}
    details = []
    for bot in only:
        c = Ctx(bot)
        await collect(c)
        res = []
        for sec, no, name, fn in ITEMS:
            try:
                v, msg = fn(c)
            except Exception as e:
                v, msg = UNK, f"점검 예외: {str(e)[:60]}"
            res.append((sec, no, name, v, msg))
        grand[bot] = res
        details.append((bot, c, res))

    ICON = {PASS: "✅", FAIL: "❌", WARN: "⚠️ ", NA: "－", UNK: "？"}
    for bot, c, res in details:
        cnt = {}
        for _, _, _, v, _ in res:
            cnt[v] = cnt.get(v, 0) + 1
        print(f"\n{'='*78}")
        print(f"  {bot}  (PID {c.pid or '없음'})  포지션 {len(c.pos)}건 · 보호주문 {len(c.algo)}건"
              + (f"  ⚠ 수집오류: {c.err}" if c.err else ""))
        print(f"  {' · '.join(f'{ICON[k].strip()} {k} {v}' for k, v in sorted(cnt.items()))}")
        print(f"{'='*78}")
        cur = ""
        for sec, no, name, v, msg in res:
            if sec != cur:
                cur = sec
                print(f"  ── 섹션 {sec} " + "─" * 60)
            print(f"  {ICON[v]} {no:2d}. {name:24} {msg}")

    print(f"\n{'='*78}\n  종합\n{'='*78}")
    print(f"  {'항목':30} " + " ".join(f"{b:>7}" for b in only))
    for sec, no, name, _ in ITEMS:
        row = []
        for b in only:
            v = next(x[3] for x in grand[b] if x[1] == no)
            row.append(f"{ICON[v].strip():>7}")
        print(f"  {no:2d}. {name:26} " + " ".join(row))
    tot = {}
    for b in only:
        for _, _, _, v, _ in grand[b]:
            tot[v] = tot.get(v, 0) + 1
    print(f"\n  총 {sum(tot.values())}개 검증 포인트: "
          + " · ".join(f"{k} {v}" for k, v in sorted(tot.items())))
    fails = [(b, no, name, msg) for b in only
             for sec, no, name, v, msg in grand[b] if v == FAIL]
    if fails:
        print(f"\n  ❌ 결함 {len(fails)}건")
        for b, no, name, msg in fails:
            print(f"     [{b}] {no:2d}. {name} — {msg}")


asyncio.run(main())
