#!/usr/bin/env python3
"""
profit_guard.py — 수익성 워치독 (1단계 심층진단 + 2단계 손실억제 자동조치)

일평균수익률이 임계치 아래로 떨어진 봇을 골라 ①왜 손실인지 심층 진단하고,
②손실을 줄이는 방향의 제한된 조치만 자동 적용한 뒤 디스코드로 보고한다.

설계 원칙
─────────
* "수익을 늘리는 변경"은 하지 않는다. 타임프레임·손익비·전략 교체 등은 짧은 표본에서
  판단이 자주 뒤집혀(실측: 백테스트 1h +14.9%/월 → 실거래 25시간 0건) 자동화가 위험하다.
  본 스크립트는 **손실을 줄이는 방향의 되돌리기 쉬운 조치**만 수행한다.
* 모든 조치는 표본 조건(최소 거래수·경과일·설정변경 후 경과)을 통과해야 발동한다.
* 조치 1회당 봇당 1건만, 쿨다운을 두고 적용한다.
* 모든 판단 근거와 조치를 디스코드로 발송하고 state 파일에 남긴다.
* KILL_SWITCH 파일이 있으면 조치를 전면 중단한다(진단·알림만 수행).

실행
────
    python3 profit_guard.py            # 진단 + 조치 + 알림
    python3 profit_guard.py --dry-run  # 진단 + 알림만 (조치 없음)
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

STATE_PATH   = os.path.join(_DIR, "profit_guard_state.json")
LOG_PATH     = os.path.join(_DIR, "profit_guard.log")
KILL_SWITCH  = os.path.join(_DIR, "profit_guard.OFF")

# ── 발동 임계 ────────────────────────────────────────────────
TRIGGER_DAILY_RET   = -1.0    # 일평균수익률(%) 이 값 미만이면 진단 대상
MIN_CLOSED_TRADES   = 20      # 표본 하한 — 이보다 적으면 노이즈로 보고 건너뜀
MIN_ELAPSED_DAYS    = 2.0     # 초기화 후 최소 경과일
MIN_HOURS_SINCE_CFG = 12.0    # config.json 최종 변경 후 최소 경과시간
                              #  (사양을 막 바꾼 봇을 곧바로 재조정하지 않기 위함)

# ── 2단계 조치 임계 ──────────────────────────────────────────
SYM_MIN_TRADES      = 5       # 종목 블랙리스트 판정 최소 거래수
SYM_MAX_WINRATE     = 20.0    # 이 승률(%) 미만이면 블랙리스트 후보
LEV_CUT_DAILY_RET   = -2.0    # 이 아래면 레버리지 1단계 축소
LEV_FLOOR           = 5       # 레버리지 하한 (이 아래로는 내리지 않음)
LEV_STEPS           = [11, 8, 5]
HALT_DAILY_RET      = -3.0    # 이 아래면 자동매매 OFF
ACTION_COOLDOWN_H   = 12.0    # 같은 봇에 조치를 다시 적용하기까지 최소 간격

# ── 복원(제재 해제) 임계 ─────────────────────────────────────
# 제재는 쉽게, 복원은 까다롭게 — 조임↔풂 반복(플립플롭)을 막는 히스테리시스.
RESTORE_DAILY_RET   = 0.5     # 일평균이 이 값 이상이어야 복원 검토 (제재 임계 -1%보다 확실히 높게)
RESTORE_MIN_HOURS   = 24.0    # 마지막 조치 후 최소 경과시간
HALT_REARM_HOURS    = 24.0    # 자동매매 정지 재개 대기(누적 정지 횟수만큼 배수: 24h→48h→수동)

BOTS = ["8401", "8402", "8403", "8404", "8405", "8407", "8408", "8409"]


# ── 유틸 ─────────────────────────────────────────────────────
def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    line = f"[{now_str()}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default if default is not None else {}


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def post_discord(content):
    """discord_alert의 웹훅 전송을 재사용. 실패해도 조치 흐름은 계속한다."""
    try:
        import discord_alert
        ok, info = discord_alert._post(content)
        if not ok:
            log(f"[DISCORD] 전송 실패: {info}")
        return ok
    except Exception as e:
        log(f"[DISCORD] 전송 예외: {e}")
        return False


# ── 지표 수집 ────────────────────────────────────────────────
def bot_metrics(bot):
    """stats.json 기반 핵심 지표. 거래소 호출 없이 파일만 읽는다."""
    folder = f"/Users/l/project/{bot}"
    s = load_json(os.path.join(folder, "data", "stats.json"))
    cfg_path = os.path.join(folder, "config.json")
    c = load_json(cfg_path)
    seed = float(s.get("seed_money") or 0.0)
    pnl = float(s.get("total_pnl_usdt") or 0.0)
    ps = (s.get("perf_start_time") or "").replace("T", " ")[:19]
    days = None
    if ps:
        try:
            days = max(0.01, (time.time() - time.mktime(time.strptime(ps, "%Y-%m-%d %H:%M:%S"))) / 86400.0)
        except ValueError:
            days = None
    cum_ret = (pnl / seed * 100.0) if seed > 0 else None
    daily_ret = (cum_ret / days) if (cum_ret is not None and days) else None
    try:
        cfg_age_h = (time.time() - os.path.getmtime(cfg_path)) / 3600.0
    except OSError:
        cfg_age_h = 999.0
    return {
        "bot": bot, "folder": folder, "cfg": c, "cfg_path": cfg_path, "perf_start": ps,
        "seed": seed, "pnl": pnl, "days": days,
        "cum_ret": cum_ret, "daily_ret": daily_ret, "cfg_age_h": cfg_age_h,
        "wins": int(s.get("total_wins") or 0), "losses": int(s.get("total_losses") or 0),
        "auto": bool(c.get("AUTO_TRADING")), "lev": int(c.get("LEVERAGE") or 0),
    }


def closed_rows(folder, perf_start=""):
    """trade_history.csv에서 청산 행만 (심볼, 손익, 수수료, 청산유형, 매매모드) 추출.

    perf_start(통계 초기화 시각) 이후 행만 센다. 이 필터가 없으면 초기화 이전 이력까지
    섞여 stats.json과 건수·손익이 전혀 달라진다(8402 실측: CSV 97건 +7.19 vs stats 26건 -0.77).
    """
    path = os.path.join(folder, "data", "trade_history.csv")
    out = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if (r.get("유형") or r.get("type") or "").strip() != "청산":
                    continue
                ts = (r.get("시간") or r.get("timestamp") or "").strip()
                if perf_start and ts and ts < perf_start:
                    continue
                try:
                    pnl = float(r.get("수익(USDT)") or r.get("pnl_usdt") or 0.0)
                except ValueError:
                    continue
                try:
                    fee = abs(float(r.get("수수료(USDT)") or 0.0))
                except ValueError:
                    fee = 0.0
                out.append({
                    "symbol": (r.get("심볼") or r.get("symbol") or "?").strip(),
                    "pnl": pnl,
                    "fee": fee,
                    "exit_type": (r.get("청산유형") or r.get("exit_type") or "?").strip(),
                    "mode": (r.get("매매모드") or r.get("trade_mode") or "?").strip(),
                })
    except OSError:
        pass
    return out


def diagnose(m):
    """심층 진단 — 종목별·청산유형별·방향별 손익과 수수료 부담을 뽑는다."""
    rows = closed_rows(m["folder"], m.get("perf_start", ""))
    if not rows:
        return None

    by_sym = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    by_exit = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    by_mode = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    for r in rows:
        for d, k in ((by_sym, "symbol"), (by_mode, "mode")):
            d[r[k]]["n"] += 1
            d[r[k]]["pnl"] += r["pnl"]
            if r["pnl"] > 0:
                d[r[k]]["w"] += 1
        by_exit[r["exit_type"]]["n"] += 1
        by_exit[r["exit_type"]]["pnl"] += r["pnl"]

    gross = sum(r["pnl"] for r in rows)
    # 수수료는 CSV의 실측값을 우선 쓰고, 기록이 비어 있을 때만 0.1%/건으로 근사한다.
    fee_real = sum(r["fee"] for r in rows)
    if fee_real > 0:
        fee_est = fee_real
    else:
        notional = float(m["cfg"].get("MARGIN_USDT") or 0) * max(1, m["lev"])
        fee_est = 0.001 * notional * len(rows)

    losers = sorted(
        [(s, v) for s, v in by_sym.items()
         if v["n"] >= SYM_MIN_TRADES and (v["w"] / v["n"] * 100.0) < SYM_MAX_WINRATE and v["pnl"] < 0],
        key=lambda x: x[1]["pnl"])
    return {"rows": len(rows), "by_sym": by_sym, "by_exit": by_exit, "by_mode": by_mode,
            "gross": gross, "fee_est": fee_est, "losers": losers}


# ── 2단계 조치 ───────────────────────────────────────────────
def apply_config(m, changes, reason, dry):
    """config.json을 백업 후 갱신. 변경 전후를 함께 반환한다."""
    if dry:
        return {k: (m["cfg"].get(k), v) for k, v in changes.items()}
    shutil.copy(m["cfg_path"], m["cfg_path"] + f".bak_pguard_{time.strftime('%Y%m%d_%H%M')}")
    c = load_json(m["cfg_path"])
    before = {k: c.get(k) for k in changes}
    c.update(changes)
    save_json(m["cfg_path"], c)
    log(f"[{m['bot']}] config 변경 ({reason}): {before} → {changes}")
    return {k: (before[k], changes[k]) for k in changes}


def decide_action(m, diag, state):
    """되돌리기 쉬운 손실억제 조치 1건을 고른다. 없으면 None.

    적용한 제재는 state의 restrictions 스택에 (키·이전값·현재값)으로 쌓아 두고,
    수익성이 회복되면 decide_restore()가 역순으로 하나씩 되돌린다.
    """
    st = state.get(m["bot"], {})
    if time.time() - st.get("last_action_ts", 0) < ACTION_COOLDOWN_H * 3600:
        return None, "조치 쿨다운 중"

    dr = m["daily_ret"]

    # ① 최우선: 심각한 손실 → 자동매매 정지
    if dr is not None and dr < HALT_DAILY_RET and m["auto"]:
        return ({"AUTO_TRADING": False},
                f"일평균 {dr:+.2f}% < {HALT_DAILY_RET}% — 자동매매 긴급 정지",
                {"kind": "halt", "key": "AUTO_TRADING", "before": True, "after": False}), None

    # ② 손실 집중 종목 블랙리스트
    if diag and diag["losers"]:
        sym, v = diag["losers"][0]
        bl = list(m["cfg"].get("SYMBOL_BLACKLIST") or [])
        if sym not in bl:
            wr = v["w"] / v["n"] * 100.0
            return ({"SYMBOL_BLACKLIST": bl + [sym]},
                    f"{sym} {v['n']}건 승률 {wr:.0f}% 누적 {v['pnl']:+.4f} — 블랙리스트 추가",
                    {"kind": "blacklist", "key": "SYMBOL_BLACKLIST", "symbol": sym}), None

    # ③ 레버리지 단계 축소
    if dr is not None and dr < LEV_CUT_DAILY_RET and m["lev"] > LEV_FLOOR:
        nxt = max([s for s in LEV_STEPS if s < m["lev"]] or [LEV_FLOOR])
        return ({"LEVERAGE": nxt},
                f"일평균 {dr:+.2f}% < {LEV_CUT_DAILY_RET}% — 레버리지 {m['lev']}→{nxt} 축소",
                {"kind": "leverage", "key": "LEVERAGE", "before": m["lev"], "after": nxt}), None

    return None, "해당 조치 없음"


def decide_restore(m, state):
    """수익성이 회복되면 걸어둔 제재를 **역순으로 1건** 되돌린다.

    제재는 쉽게 걸고 복원은 까다롭게(히스테리시스) 만들어 조임↔풂이 반복되는 걸 막는다.
      · 복원 임계(+0.5%)를 제재 임계(-1%)보다 확실히 높게 둔다
      · 마지막 조치 후 RESTORE_MIN_HOURS 경과해야 한다
      · 표본 조건은 제재와 동일하게 적용한다

    자동매매 정지는 예외다. 멈춰 있으면 새 거래가 없어 지표가 개선될 수 없으므로
    지표 기반으로는 영원히 복구되지 않는다. 그래서 **시간 기반**으로 재개하되,
    반복 정지될수록 재개까지의 대기를 늘리고(24h→48h) 3회째부터는 사람이 풀게 한다.
    """
    st = state.get(m["bot"], {})
    stack = list(st.get("restrictions") or [])
    if not stack:
        return None, None

    top = stack[-1]
    since_h = (time.time() - st.get("last_action_ts", 0)) / 3600.0

    if top["kind"] == "halt":
        halts = int(st.get("halt_count", 1))
        if halts >= 3:
            return None, f"자동매매 3회째 정지 — 자동 재개 안 함(수동 확인 필요, {since_h:.1f}h 경과)"
        need = HALT_REARM_HOURS * halts        # 1회 24h · 2회 48h
        if since_h < need:
            return None, f"자동매매 재개 대기 {since_h:.1f}/{need:.0f}h"
        return ({"AUTO_TRADING": True},
                f"정지 후 {since_h:.1f}h 경과 — 자동매매 재개 (누적 정지 {halts}회)", top), None

    dr = m["daily_ret"]
    if dr is None or dr < RESTORE_DAILY_RET:
        return None, None                      # 아직 회복 못 함 — 조용히 유지
    if since_h < RESTORE_MIN_HOURS:
        return None, f"복원 대기 {since_h:.1f}/{RESTORE_MIN_HOURS:.0f}h (일평균 {dr:+.2f}%)"

    if top["kind"] == "leverage":
        return ({"LEVERAGE": top["before"]},
                f"일평균 {dr:+.2f}% 회복 — 레버리지 {top['after']}→{top['before']} 원복", top), None
    if top["kind"] == "blacklist":
        bl = [s for s in (m["cfg"].get("SYMBOL_BLACKLIST") or []) if s != top["symbol"]]
        return ({"SYMBOL_BLACKLIST": bl},
                f"일평균 {dr:+.2f}% 회복 — {top['symbol']} 블랙리스트 해제", top), None
    return None, None


def restart_bot(bot, dry):
    if dry:
        return True, "(dry-run)"
    try:
        r = subprocess.run(["bash", "run.sh"], cwd=f"/Users/l/project/{bot}",
                           capture_output=True, text=True, timeout=180)
        return r.returncode == 0, (r.stdout or r.stderr or "")[-200:]
    except Exception as e:
        return False, str(e)[:200]


# ── 리포트 ───────────────────────────────────────────────────
def build_report(m, diag, action, applied, restarted, is_restore=False, pending=None):
    L = [f"🩺 **[수익성 워치독] {m['bot']}**",
         f"일평균 **{m['daily_ret']:+.2f}%** · 누적 {m['cum_ret']:+.2f}% "
         f"({m['pnl']:+.4f} / 시드 ${m['seed']:.2f}) · {m['days']:.1f}일 · {m['wins']}승{m['losses']}패"]
    if diag:
        L.append(f"청산 {diag['rows']}건 · 총손익 {diag['gross']:+.4f} · 수수료추정 {diag['fee_est']:.4f}")
        if diag["fee_est"] > abs(diag["gross"]):
            L.append("⚠️ 수수료가 총손익보다 큽니다 — 과회전 의심")
        worst = sorted(diag["by_sym"].items(), key=lambda x: x[1]["pnl"])[:3]
        L.append("손실 상위: " + ", ".join(
            f"{s.split('/')[0]} {v['n']}건 {v['w']}승 {v['pnl']:+.3f}" for s, v in worst))
        ex = sorted(diag["by_exit"].items(), key=lambda x: x[1]["pnl"])[:3]
        L.append("청산유형: " + ", ".join(f"{k} {v['n']}건 {v['pnl']:+.3f}" for k, v in ex))
        md = ", ".join(f"{k} {v['n']}건 {v['w']}승 {v['pnl']:+.3f}" for k, v in diag["by_mode"].items())
        if md:
            L.append("방향별: " + md)
    if action:
        icon = "♻️ **복원**" if is_restore else "🔧 **조치**"
        L.append(f"{icon}: {action[1]}")
        if applied:
            L.append("변경: " + ", ".join(f"{k} {a} → {b}" for k, (a, b) in applied.items()))
        L.append(f"재기동: {'성공' if restarted else '실패/생략'}")
    else:
        L.append("🔧 조치 없음 (조건 미해당)")
    if pending:
        L.append(f"남은 제재 {len(pending)}건: " + ", ".join(
            p.get("symbol") or f"{p['key']} {p.get('after')}" for p in pending))
    return "```\n" + "\n".join(L) + "\n```"


# ── 전략·설정 변경 감지 ──────────────────────────────────────
WATCH_KEYS = ["TIMEFRAME", "USE_BLUEFROG", "USE_AUTO_MODE_SWITCH", "AUTO_TRADING",
              "LEVERAGE", "MARGIN_USDT", "MAX_POSITIONS", "SCAN_TOP_N",
              "MIN_VOLUME_USDT", "MAX_HOLDING_HOURS", "DBB_TP_RR", "DIV_TP_RR"]
_LABEL = {"TIMEFRAME": "타임프레임", "USE_BLUEFROG": "매매방향(역매매)",
          "USE_AUTO_MODE_SWITCH": "자동반전", "AUTO_TRADING": "자동매매",
          "LEVERAGE": "레버리지", "MARGIN_USDT": "증거금", "MAX_POSITIONS": "최대포지션",
          "SCAN_TOP_N": "스캔종목수", "MIN_VOLUME_USDT": "거래대금하한",
          "MAX_HOLDING_HOURS": "최대보유시간", "DBB_TP_RR": "손익비(DBB)",
          "DIV_TP_RR": "손익비(DIV)", "__strategy__": "전략코드", "__blacklist__": "블랙리스트"}


def config_fingerprint(m):
    """감시 대상 설정값 + 전략코드 해시로 지문을 만든다."""
    import hashlib
    fp = {k: m["cfg"].get(k) for k in WATCH_KEYS}
    fp["__blacklist__"] = len(m["cfg"].get("SYMBOL_BLACKLIST") or [])
    try:
        with open(os.path.join(m["folder"], "core", "strategy.py"), "rb") as f:
            fp["__strategy__"] = hashlib.md5(f.read()).hexdigest()[:10]
    except OSError:
        fp["__strategy__"] = None
    return fp


def check_config_changes(metrics, state, dry):
    """직전 지문과 비교해 바뀐 항목만 디스코드로 알린다."""
    prev_all = state.get("__fingerprints__", {})
    changed_bots = []
    for m in metrics:
        bot = m["bot"]
        cur = config_fingerprint(m)
        prev = prev_all.get(bot)
        if prev is None:                       # 최초 실행 — 기준선만 저장
            prev_all[bot] = cur
            continue
        diffs = [(k, prev.get(k), cur.get(k)) for k in cur if prev.get(k) != cur.get(k)]
        if diffs:
            lines = [f"⚙️ **[설정 변경 감지] {bot}**"]
            for k, a, b in diffs:
                name = _LABEL.get(k, k)
                if k == "__strategy__":
                    lines.append(f"  {name}: 파일이 교체됨 ({a} → {b})")
                else:
                    lines.append(f"  {name}: {a} → {b}")
            post_discord("```\n" + "\n".join(lines) + "\n```")
            log(f"[{bot}] 설정 변경 감지 {len(diffs)}건 → 알림 발송")
            changed_bots.append(bot)
        prev_all[bot] = cur
    if not dry:
        state["__fingerprints__"] = prev_all
    return changed_bots


def main():
    dry = "--dry-run" in sys.argv
    killed = os.path.exists(KILL_SWITCH)
    if killed:
        log("KILL_SWITCH 감지 — 진단·알림만 수행하고 조치는 건너뜁니다")
    state = load_json(STATE_PATH, {})

    log(f"수익성 점검 시작 (dry_run={dry}, kill_switch={killed})")

    # 전략·설정 변경 감지는 수익성과 무관하게 매 주기 먼저 수행한다
    # (대시보드 토글·자동반전·내 조치 등 어떤 경로의 변경이든 놓치지 않기 위함)
    all_metrics = [bot_metrics(b) for b in BOTS]
    check_config_changes(all_metrics, state, dry)

    for m in all_metrics:
        bot = m["bot"]
        if m["daily_ret"] is None:
            continue
        closed = m["wins"] + m["losses"]
        st = state.setdefault(bot, {})
        stack = list(st.get("restrictions") or [])

        # ── 회복 경로: 제재가 걸려 있으면 손실 판정보다 먼저 복원을 검토한다 ──
        # (자동매매 정지는 거래가 없어 지표가 개선될 수 없으므로 시간 기반으로 재개한다)
        if stack and not killed:
            r_action, r_why = decide_restore(m, state)
            if r_action:
                applied = apply_config(m, r_action[0], r_action[1], dry)
                restarted, info = restart_bot(bot, dry)
                log(f"[{bot}] ♻️ 복원: {r_action[1]} · 재기동 {'성공' if restarted else '실패'} {info}")
                if not dry:
                    stack.pop()
                    st["restrictions"] = stack
                    st["last_action_ts"] = time.time()
                    st["last_action"] = "복원: " + r_action[1]
                    st["at"] = now_str()
                post_discord(build_report(m, diagnose(m), r_action, applied, restarted,
                                          is_restore=True, pending=stack))
                continue
            if r_why:
                log(f"[{bot}] {r_why}")

        # 표본·안정화 조건 — 하나라도 미달이면 건너뛴다
        if m["daily_ret"] >= TRIGGER_DAILY_RET:
            continue
        skips = []
        if closed < MIN_CLOSED_TRADES:
            skips.append(f"거래 {closed}건 < {MIN_CLOSED_TRADES}")
        if m["days"] < MIN_ELAPSED_DAYS:
            skips.append(f"경과 {m['days']:.1f}일 < {MIN_ELAPSED_DAYS}")
        if m["cfg_age_h"] < MIN_HOURS_SINCE_CFG:
            skips.append(f"설정변경 {m['cfg_age_h']:.1f}h 전 < {MIN_HOURS_SINCE_CFG}h")
        if skips:
            log(f"[{bot}] 일평균 {m['daily_ret']:+.2f}% 이나 표본 미달로 보류 — {', '.join(skips)}")
            continue
        log(f"[{bot}] 발동 — 일평균 {m['daily_ret']:+.2f}% · 청산 {closed}건 · 경과 {m['days']:.1f}일")

        diag = diagnose(m)
        action, why = (None, None)
        if not killed:
            action, why = decide_action(m, diag, state)
        applied, restarted = None, False
        if action:
            applied = apply_config(m, action[0], action[1], dry)
            restarted, info = restart_bot(bot, dry)
            log(f"[{bot}] 재기동 {'성공' if restarted else '실패'} {info}")
            if not dry:
                rec = dict(action[2])
                rec["ts"] = time.time()
                stack.append(rec)                 # 복원용 제재 스택에 적재
                st["restrictions"] = stack
                st["last_action_ts"] = time.time()
                st["last_action"] = action[1]
                st["at"] = now_str()
                if rec["kind"] == "halt":
                    st["halt_count"] = int(st.get("halt_count", 0)) + 1
        elif why:
            log(f"[{bot}] {why}")

        post_discord(build_report(m, diag, action, applied, restarted, pending=stack))
        log(f"[{bot}] 진단 리포트 발송 완료")

    if not dry:
        save_json(STATE_PATH, state)
    log("수익성 점검 종료")


if __name__ == "__main__":
    main()
