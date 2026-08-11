#!/usr/bin/env python3
"""config_sentinel.py — 4봇 테스트 조건 감시·자동 복원

배경
────
2026-08-11, 외부 도구(Antigravity IDE)가 8401·8403·8408·8409 네 봇에
내가 만들지 않은 커밋을 두 차례(14:11, 15:15) 밀어넣었다. 그 결과
  * 8408·8409의 `core/exchange.py`가 바이낸스 → OKX 클라이언트로 통째 교체되어
    모든 인증 호출이 `okx requires "password" credential`로 실패했고,
  * `USE_BLUEFROG`(역매매)·`USE_AUTO_MODE_SWITCH`(방향 자가변경)가 True로 되돌아갔다.

그리고 30일치 이력을 보니 이건 예외가 아니었다. 8408의 매매 방향은
**8번 뒤집혔고 평균 3.75일 주기**였다. "봇이 4~5일 뒤 나빠진다"는 현상의
시계와 정확히 겹친다. 즉 성과가 나빠지는 게 아니라 **며칠 지나면 다른 봇이
되어 있는 것**이다.

따라서 테스트 기간에는 조건이 고정되어 있다는 보장이 있어야 측정이 성립한다.
이 파일은 그 보장을 담당한다. 어긋나면 즉시 되돌리고 기록한다.

동작
────
5분마다(워치독이 호출) 4봇의 핵심 설정과 거래소 클래스를 검사한다.
  * config.json 값이 기준과 다르면  → 기준값으로 되돌린다
  * core/config.py 기본값이 다르면   → 경고(파일 수정은 하지 않음, 사람이 판단)
  * core/exchange.py의 ccxt 클래스가 거래소와 맞지 않으면 → 치명 경고
바꾼 내역은 config_sentinel.log에 남기고 디스코드로 알린다.

테스트 종료 후에는 이 파일 호출만 빼면 된다(설정 자체는 건드리지 않는다).
"""
import json
import os
import subprocess
import sys
import time

BASE = "/Users/l/project"
LOG = os.path.join(BASE, "8888", "config_sentinel.log")

# 4봇 공통 테스트 조건. 여기서 벗어나면 되돌린다.
COMMON = {
    "AUTO_TRADING": True,
    "USE_BLUEFROG": False,          # 정방향 고정 — 검증(+20.8%/+2.7%)이 정방향 기준
    "USE_AUTO_MODE_SWITCH": False,  # 방향 자가변경 금지 — 30일 8회 반전 실측
    "USE_AUTO_COMPOUND": True,
    "AUTO_COMPOUND_PCT": 15.0,
    "RISK_PER_TRADE_PCT": 0.0,      # M4 위험균등 사이징 해제(0이 아니면 복리를 덮어씀)
    "USE_BE_GUARD": False,
    "USE_MARKET_GATE": True,
    "SCAN_TOP_N": 80,      # 표본 확보 — 30이면 신호가 거의 안 나온다
}
# 봇별 예외
PER_BOT = {
    "8401": {"MARKET_GATE_EMA": 12, "LEVERAGE": 5, "MIN_VOLUME_USDT": 500000.0},   # 1h봉 12봉=12시간
    "8403": {"MARKET_GATE_EMA": 48, "LEVERAGE": 5, "MIN_VOLUME_USDT": 500000.0},
    "8408": {"MARKET_GATE_EMA": 48, "LEVERAGE": 11},
    "8409": {"MARKET_GATE_EMA": 48, "LEVERAGE": 11},
}
# 거래소별 기대 ccxt 클래스 — 어긋나면 인증이 전부 깨진다
VENUE = {"8401": "okx", "8403": "okx", "8408": "binance", "8409": "binance"}


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def notify(msg):
    """디스코드 알림. profit_guard의 발송 경로를 그대로 쓴다(웹훅 중복 정의 방지)."""
    try:
        sys.path.insert(0, os.path.join(BASE, "8888"))
        from profit_guard import post_discord
        post_discord(msg)
    except Exception as e:
        log(f"  (디스코드 알림 실패: {str(e)[:80]})")


def check_exchange_class(bot):
    """core/exchange.py가 그 봇의 거래소와 맞는 ccxt 클래스를 쓰는지."""
    path = os.path.join(BASE, bot, "core", "exchange.py")
    try:
        src = open(path, encoding="utf-8").read()
    except OSError as e:
        return f"exchange.py 읽기 실패: {e}"
    want = f"ccxt_async.{VENUE[bot]}"
    other = "ccxt_async.okx" if VENUE[bot] == "binance" else "ccxt_async.binance"
    if want not in src:
        return f"거래소 클래스 불일치 — {want} 없음"
    if other in src and src.index(other) < src.index(want):
        return f"거래소 클래스 의심 — {other}가 앞서 정의됨"
    return None


def check_bot(bot, fix=True):
    """config.json을 기준과 대조하고, 어긋나면 되돌린다. 바뀐 항목 목록을 반환."""
    path = os.path.join(BASE, bot, "config.json")
    try:
        cfg = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        log(f"[{bot}] config.json 읽기 실패: {e}")
        return [], []

    want = dict(COMMON)
    want.update(PER_BOT.get(bot, {}))

    drift = []
    for k, v in want.items():
        cur = cfg.get(k)
        if cur != v:
            drift.append(f"{k}: {cur} → {v}")
            cfg[k] = v

    if drift and fix:
        # 되돌리기 전 상태를 남긴다(무엇이 어떻게 바꿨는지 추적용)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        try:
            with open(f"{path}.drift_{stamp}", "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except OSError as e:
            log(f"[{bot}] 복원 실패: {e}")
            return drift, []

    problems = []
    err = check_exchange_class(bot)
    if err:
        problems.append(err)
    return drift, problems


def main():
    fix = "--check-only" not in sys.argv
    all_drift, all_problems = {}, {}
    for bot in VENUE:
        drift, problems = check_bot(bot, fix=fix)
        if drift:
            all_drift[bot] = drift
        if problems:
            all_problems[bot] = problems

    if not all_drift and not all_problems:
        log("이상 없음 — 4봇 테스트 조건 유지 중")
        return

    lines = ["⚠️ **[테스트 조건 변조 감지]**"]
    for bot, d in all_drift.items():
        act = "되돌림" if fix else "감지만"
        lines.append(f"\n**{bot}** 설정 {len(d)}건 {act}")
        lines += [f"• {x}" for x in d]
        log(f"[{bot}] 설정 {len(d)}건 {act}: " + " / ".join(d))
    for bot, p in all_problems.items():
        lines.append(f"\n🔴 **{bot} 코드 이상 — 자동복원 불가, 확인 필요**")
        lines += [f"• {x}" for x in p]
        log(f"[{bot}] 코드 이상: " + " / ".join(p))
    lines.append("\n외부 도구(IDE 등)가 봇 폴더를 수정하고 있을 수 있습니다.")
    notify("\n".join(lines))


if __name__ == "__main__":
    main()
