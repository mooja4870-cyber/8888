#!/usr/bin/env python3
"""exchange_pnl.py — 거래소 원장 기준 실현손익 조회 (성과 지표의 단일 출처)

거래이력 CSV의 `수익(USDT)`를 신뢰하지 않는다. 초저가 코인에서 가격 정밀도가
소실돼 손익 부호가 뒤집힌다. 실측(2026-08-12 8403 BONK):

    CSV     진입 2.321e-06 → 청산 **2e-06**        수익 **+$2.9853** (+69.15%)
    거래소  진입 0.00000232 → 청산 0.000002332     실현 **−$0.1332**

청산가가 유효숫자 1자리로 뭉개져 숏 포지션의 손실이 거대 이익으로 기록됐다.
이 한 건이 계좌의 10%에 해당하는 $3.12 오차를 만들었고, 그 탓에
"8403 +$2.26 수익"으로 보고됐으나 실제로는 −$1.13 손실이었다.

정상 가격대 종목(LINK $8.7, AVAX $6.3 등)은 CSV도 맞으므로 CSV가 늘 틀린 건
아니지만, 저가 코인이 하나만 섞여도 통계 전체가 무너진다. 그래서 성과 판정은
거래소가 말하는 값으로만 한다.

조회 경로
    OKX      privateGetAccountPositionsHistory — 청산 포지션별 realizedPnl(수수료·펀딩 포함)
    바이낸스  fapiPrivateGetIncome — REALIZED_PNL + COMMISSION + FUNDING_FEE

봇마다 `core` 패키지가 다르므로 **봇당 별도 프로세스**로 조회한다. 한 프로세스에서
여러 봇을 임포트하면 먼저 로드된 모듈이 캐시돼 다른 봇 값이 그대로 나온다
(실측: 8403이 8401과 동일 수치로 출력됨).

결과는 짧게 캐시한다. 대시보드가 매초 새로고침해도 거래소를 두들기지 않도록.
"""
import json
import os
import subprocess
import sys
import threading
import time

BASE = "/Users/l/project"
HELPER = os.path.join(BASE, "8888", "lab", "_one_bot_report.py")
# [2026-08-21] 8402·8404 추가 (세력흔적 A/B 대조군).
VENUE = {"8401": "okx", "8402": "okx", "8403": "okx", "8404": "okx",
         "8408": "binance", "8409": "binance"}
CACHE_TTL = 60.0          # 초. 거래소 호출 억제용
_cache = {}
_lock = threading.Lock()


def fetch_one(bot, timeout=90):
    """봇 하나의 거래소 원장 성과. 실패 시 None."""
    venue = VENUE.get(bot)
    if not venue or not os.path.exists(HELPER):
        return None
    py = os.path.join(BASE, bot, "venv", "bin", "python3")
    if not os.path.exists(py):
        py = sys.executable
    try:
        r = subprocess.run([py, HELPER, os.path.join(BASE, bot), venue],
                           capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    for line in (r.stdout or "").splitlines():
        if line.startswith("JSON"):
            try:
                return json.loads(line[4:])
            except ValueError:
                return None
    return None


def get(bot, max_age=CACHE_TTL):
    """캐시된 성과. 갱신 실패 시 마지막 성공값을 계속 쓴다(화면 공백 방지)."""
    with _lock:
        hit = _cache.get(bot)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    fresh = fetch_one(bot)
    if fresh is None:
        return hit[1] if hit else None
    with _lock:
        _cache[bot] = (time.time(), fresh)
    return fresh


def get_all(bots=None, max_age=CACHE_TTL):
    return {b: get(b, max_age) for b in (bots or list(VENUE))}


if __name__ == "__main__":
    rows = [r for r in (get(b, 0) for b in VENUE) if r]
    if not rows:
        print("  조회 실패")
        raise SystemExit(1)
    print(f"\n  ══ 거래소 원장 기준 성과 ══  ({rows[0]['ps']} 이후 {rows[0]['hours']:.1f}시간)")
    print("  {:<6}{:>7}{:>11}{:>10}{:>9}{:>10}{:>9}{:>9}".format(
        "봇", "시드", "실현손익", "미실현", "총잔고", "시드대비", "승패", "수수료"))
    print("  " + "─" * 72)
    ts = tr = tu = tt = 0.0
    for r in rows:
        ret = (r["total"] - r["seed"]) / r["seed"] * 100 if r["seed"] else 0
        ts += r["seed"]; tr += r["real"]; tu += r["unreal"]; tt += r["total"]
        print("  {:<6}{:>7.2f}{:>+11.4f}{:>+10.4f}{:>9.2f}{:>+9.2f}%{:>9}{:>9.4f}".format(
            r["bot"], r["seed"], r["real"], r["unreal"], r["total"], ret,
            "{}승{}패".format(r["wins"], r["losses"]), r["fee"]))
    print("  " + "─" * 72)
    print("  {:<6}{:>7.2f}{:>+11.4f}{:>+10.4f}{:>9.2f}{:>+9.2f}%".format(
        "합계", ts, tr, tu, tt, (tt - ts) / ts * 100 if ts else 0))
    print("\n  ── 검산 (시드 + 실현 + 미실현 = 총잔고) ──")
    for r in rows:
        calc = r["seed"] + r["real"] + r["unreal"]
        gap = r["total"] - calc
        print("  {}: {:.4f} vs 실제 {:.4f} · 차이 {:+.4f} {}".format(
            r["bot"], calc, r["total"], gap, "✅" if abs(gap) < 0.1 else "⚠️"))
