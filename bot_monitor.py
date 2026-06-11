#!/usr/bin/env python3
"""
bot_monitor.py — 10개 봇 자동 진단 엔진 (mooja 지시, v0.9.5~)
무포지션 상태로 일정 시간 이상 무진입인 봇을 골라, 진입 차단 원인을 진단한다.

핵심 설계:
- 모든 봇 공통 파일(config.json / data/active_positions.json / data/stats.json /
  data/trade_history.csv)만으로 1차(결정적) 진단 → 봇 구조 이질성에 견고.
- 로그(diagnostic.log 등 봇별 상이)는 있으면 best-effort 2차 스캔.
- 분류: DOWN(프로세스 다운) / ERROR(오류로 차단) / BLOCKED(필터·신호 문제 의심)
        / NORMAL_HALT(쿨다운·일일한도·세션블록 등 정상 정지) / NO_SIGNAL(그냥 신호 없음)
- 실행: python3 bot_monitor.py [무진입_임계분(기본 60)]
- 의존성 0 (표준 라이브러리만). 거래소 호출/주문/자금이동 없음 — 읽기 전용.
"""
import csv
import json
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone

BASE = "/Users/l/project"
KST = timezone(timedelta(hours=9))
IDLE_MIN_DEFAULT = 60          # 무진입 임계(분)
TAIL_BYTES = 65536             # trade_history 끝에서 읽을 바이트
LOG_TAIL_BYTES = 200000        # 로그 끝에서 스캔할 바이트
LOG_RECENT_MIN = 90            # 로그에서 '최근'으로 볼 시간(분)

BOTS = [
    ("8401_okx", 8401, "OKX"), ("8402_okx", 8402, "OKX"), ("8403_okx", 8403, "OKX"),
    ("8404_okx", 8404, "OKX"), ("8405_okx", 8405, "OKX"), ("8406_okx", 8406, "OKX"),
    ("8407_bnc", 8407, "BNC"), ("8408_bnc", 8408, "BNC"), ("8409_bnc", 8409, "BNC"),
    ("8501_bnc", 8501, "BNC"),
]

# 로그에서 찾을 어휘 (best-effort)
ERR_PAT = ("error", "오류", "traceback", "exception", "networkerror",
           "-1021", "timestamp", "실패", "insufficient")
# 신호 포착: 타임스탬프 있는 줄 + 명시적 신호 토큰만 (느슨한 '강도' 단독 매칭 제외 → 과다카운트 방지)
SIG_PAT = ("[sig]", "신호 포착", "signal found")
# 주문 실패 증거 (BLOCKED 판정의 필수 동반 조건)
FAIL_PAT = ("주문 실패", "order failed", "rejected", "마진 부족",
            "insufficient", '"code":-')
BLOCK_PAT = ("filter", "필터", "blocked", "차단", "reject")


def now_kst():
    return datetime.now(KST)


def port_alive(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def parse_dt(s):
    """'2026-06-09 22:40:30' 또는 ISO → KST aware datetime."""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace(" ", "T"))
        return d if d.tzinfo else d.replace(tzinfo=KST)
    except ValueError:
        return None


def last_entry_time(folder):
    """trade_history.csv 끝부분에서 마지막 '진입' 행의 시간 반환."""
    path = os.path.join(BASE, folder, "data", "trade_history.csv")
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            chunk = f.read().decode("utf-8-sig", errors="replace")
    except OSError:
        return None
    lines = [ln for ln in chunk.splitlines() if ln.strip()]
    last = None
    for ln in lines:
        cols = ln.split(",")
        if len(cols) < 3:
            continue
        if cols[2].strip() == "진입":
            dt = parse_dt(cols[0].strip())
            if dt and (last is None or dt > last):
                last = dt
    return last


def newest_log(folder):
    """봇 폴더/데이터에서 가장 최근 수정된 .log 경로(없으면 None)."""
    cands = []
    for d in (os.path.join(BASE, folder), os.path.join(BASE, folder, "data")):
        try:
            for fn in os.listdir(d):
                if fn.endswith(".log"):
                    p = os.path.join(d, fn)
                    cands.append((os.path.getmtime(p), p))
        except OSError:
            pass
    if not cands:
        return None
    return max(cands)[1]


def scan_log(path):
    """로그 끝부분 스캔 → {err, signal, block} 최근 발생 여부(개수)."""
    out = {"err": 0, "signal": 0, "block": 0, "fail": 0, "sample_err": ""}
    if not path:
        return out
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - LOG_TAIL_BYTES))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return out
    cutoff = now_kst() - timedelta(minutes=LOG_RECENT_MIN)
    for ln in chunk.splitlines():
        low = ln.lower()
        dt = parse_dt(ln[:19])               # 줄 앞 19자 타임스탬프
        recent = (dt is None) or (dt >= cutoff)
        if not recent:
            continue
        # 오류: 타임스탬프 없어도 카운트(오류는 형식이 불규칙) — 단 오래된 건 위 recent에서 거름
        if any(p in low for p in ERR_PAT):
            out["err"] += 1
            if not out["sample_err"]:
                out["sample_err"] = ln.strip()[:160]
        # 신호/실패/차단: 타임스탬프 있는 줄만 카운트(줄바꿈 잔여·중복 방지)
        if dt is not None:
            if any(p in low for p in SIG_PAT):
                out["signal"] += 1
            if any(p in low for p in FAIL_PAT):
                out["fail"] += 1
            if any(p in low for p in BLOCK_PAT):
                out["block"] += 1
    return out


def in_session_block(cfg):
    """SESSION_BLOCK 설정상 지금이 차단 시간대인지."""
    if not cfg.get("SESSION_BLOCK_ENABLED"):
        return False
    s, e = cfg.get("SESSION_BLOCK_START"), cfg.get("SESSION_BLOCK_END")
    if not s or not e:
        return False
    now = now_kst().strftime("%H:%M")
    if s <= e:
        return s <= now <= e
    return now >= s or now <= e   # 자정 넘김


def cooldown_active(stats):
    g = stats.get("global_cooldown_until") if stats else None
    dt = parse_dt(g)
    return bool(dt and dt > now_kst())


def diagnose(folder, port, ex, idle_min_thresh):
    cfg = load_json(os.path.join(BASE, folder, "config.json")) or {}
    stats = load_json(os.path.join(BASE, folder, "data", "stats.json")) or {}
    pos = load_json(os.path.join(BASE, folder, "data", "active_positions.json")) or {}
    name = folder.split("_")[0]

    alive = port_alive(port)
    has_pos = bool(pos)
    npos = len(pos) if isinstance(pos, dict) else 0
    le = last_entry_time(folder)
    idle_min = int((now_kst() - le).total_seconds() / 60) if le else None
    tf = cfg.get("TIMEFRAME", "?")
    auto = cfg.get("AUTO_TRADING", None)

    base = {
        "name": name, "ex": ex, "alive": alive, "has_pos": has_pos,
        "npos": npos, "idle_min": idle_min, "tf": tf, "auto": auto,
        "orders_today": stats.get("orders_today"),
    }

    # 포지션 있으면 진단 대상 아님 (정상 운용 중)
    if has_pos:
        return {**base, "verdict": "HOLDING", "reason": f"포지션 {npos}개 보유 중", "act": None}
    # 자동매매 꺼져 있으면 무진입이 당연
    if auto is False:
        return {**base, "verdict": "OFF", "reason": "AUTO_TRADING=false (의도된 정지)", "act": None}
    # 임계 미만이면 아직 정상
    if idle_min is not None and idle_min < idle_min_thresh:
        return {**base, "verdict": "OK", "reason": f"무진입 {idle_min}분 (<{idle_min_thresh}분)", "act": None}

    # 여기부터: 무포지션 + 임계 이상 무진입 → 원인 규명
    if not alive:
        return {**base, "verdict": "DOWN", "reason": "포트 무응답 — 프로세스 다운 의심",
                "act": "프로세스 재시작 필요(수동 확인) — 자동 재시작은 중복실행 위험으로 보고만"}

    if cooldown_active(stats):
        return {**base, "verdict": "NORMAL_HALT", "reason": "글로벌 쿨다운 활성 (정상, 자동 해제)", "act": None}

    # 일일 손실 한도 도달 여부
    dpl = stats.get("daily_pnl_usdt")
    dll = cfg.get("DAILY_LOSS_LIMIT_USDT")
    if dpl is not None and dll is not None and dpl <= -abs(dll):
        return {**base, "verdict": "NORMAL_HALT",
                "reason": f"일일 손실한도 도달 (오늘 {dpl:.2f} ≤ -{dll}) — 당일 정지", "act": None}

    if in_session_block(cfg):
        return {**base, "verdict": "NORMAL_HALT", "reason": "세션 블록 시간대 (정상)", "act": None}

    # 로그 best-effort
    log = scan_log(newest_log(folder))
    if log["err"] >= 3:
        return {**base, "verdict": "ERROR",
                "reason": f"최근 {LOG_RECENT_MIN}분 오류 {log['err']}건: {log['sample_err']}",
                "act": "오류 유형별 대응 필요(예: -1021=시계동기, NetworkError=연결). 자동수정 후보."}
    # BLOCKED: 신호가 실제로 떴는데(타임스탬프 동반) 주문실패가 동반된 경우만 — 오탐 방지
    if log["signal"] >= 3 and log["fail"] >= 3:
        return {**base, "verdict": "BLOCKED",
                "reason": f"최근 신호 {log['signal']}건인데 주문 실패 {log['fail']}건 — 진입 차단",
                "act": "주문실패 원인 점검(심볼 거래불가/마진/권한). 안전 시 블랙리스트 자동수정 후보."}
    if log["signal"] >= 3 and log["block"] >= 5:
        return {**base, "verdict": "BLOCKED",
                "reason": f"최근 신호 {log['signal']}건, 필터/차단 {log['block']}건 — 필터 과도 의심",
                "act": "진입 필터 완화 검토(리스크 항목 제외)"}

    # 신호 자체가 없음 / 정상 스캔 중
    note = ""
    if tf in ("1h", "4h", "1d"):
        note = f" ({tf}봉은 {idle_min_thresh}분 무진입이 정상 범주)"
    if log["signal"] >= 1:
        note += f" / 신호 {log['signal']}건 포착·정상 스캔 중"
    return {**base, "verdict": "NO_SIGNAL",
            "reason": f"진입 신호 없음 — 시장 미충족으로 추정{note}", "act": None}


def main():
    thresh = int(sys.argv[1]) if len(sys.argv) > 1 else IDLE_MIN_DEFAULT
    print(f"[bot_monitor] {now_kst().strftime('%Y-%m-%d %H:%M:%S')} KST "
          f"| 무진입 임계 {thresh}분\n" + "=" * 78)
    results = [diagnose(f, p, e, thresh) for f, p, e in BOTS]

    order = {"DOWN": 0, "ERROR": 1, "BLOCKED": 2, "NORMAL_HALT": 3,
             "NO_SIGNAL": 4, "OFF": 5, "OK": 6, "HOLDING": 7}
    results.sort(key=lambda r: order.get(r["verdict"], 9))

    icon = {"DOWN": "🔴", "ERROR": "🔴", "BLOCKED": "🟠", "NORMAL_HALT": "🟡",
            "NO_SIGNAL": "⚪", "OFF": "⚫", "OK": "🟢", "HOLDING": "🟢"}
    flagged = []
    for r in results:
        i = icon.get(r["verdict"], "❓")
        idle = f"{r['idle_min']}분" if r["idle_min"] is not None else "—"
        print(f"{i} {r['name']} [{r['ex']}/{r['tf']}] {r['verdict']:<11} "
              f"무진입{idle:<7} | {r['reason']}")
        if r["act"]:
            print(f"     ↳ 조치: {r['act']}")
        if r["verdict"] in ("DOWN", "ERROR", "BLOCKED"):
            flagged.append(r)

    print("=" * 78)
    print(f"진단 대상 문제 봇: {len(flagged)}개"
          + (f" → {', '.join(r['name'] for r in flagged)}" if flagged else " (이상 없음)"))
    return flagged


if __name__ == "__main__":
    main()
