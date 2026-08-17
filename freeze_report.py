#!/usr/bin/env python3
"""freeze_report.py — 30일 동결 기간 자동 성과 보고 (디스코드)

왜 자동인가
──────────
동결의 목적은 **손대지 않고 측정하는 것**이다. 그런데 사람이 매번 물어봐야 알 수
있으면 확인하러 들어갔다가 결국 만지게 된다. 정해진 시각에 결과만 오면 그럴 일이 없다.

보고 내용
  · 거래소 원장 기준 실적 (봇이 자체 기록한 stats.json은 믿지 않는다 — 5건의 오보 실측)
  · 동결 기준선 대비 변화
  · 중단 조건(합산 −25%) 도달 여부
  · 봇 생존·설정 드리프트

**이 스크립트는 매매에 관여하지 않는다.** 읽고 보고할 뿐이다.
"""
import json
import math
import os
import sys
import time

BASE = "/Users/l/project"
HERE = os.path.join(BASE, "8888")
sys.path.insert(0, HERE)
os.chdir(HERE)

BOTS = ["8401", "8403", "8408", "8409"]
FREEZE_START = "2026-08-16"
FREEZE_END = "2026-09-15"
SEED_TOTAL = 120.0
STOP_PCT = -25.0          # 합산 이 아래면 중단 판단을 구한다

# ── 백테-실거래 괴리 측정 ────────────────────────────────────────────────
# 이 동결의 진짜 목적은 총수익률을 보는 게 아니다. 총수익률은 30일 뒤에도
# 95% 구간 폭이 ±17%p라 아무것도 못 가린다. 반면 **건당 손익**은
# 30일 약 900건이면 표준오차 0.05%p까지 좁혀져 백테스트와의 괴리를 가린다.
# 그 괴리가 100개 봇 미스터리의 핵심이다(백테는 늘 좋고 실거래는 늘 나쁘다).
#
# 주의: 손익은 **거래소 원장만** 쓴다. trade_history.csv의 수익률로 계산하면
# 8403이 건당 −0.090%인데 원장으로는 −1.10%로 12배 어긋난다(2026-08-17 실측).
BACKTEST_PER_TRADE = 0.057   # 61종목 3925신호·게이트ON·K4.0 기준, 명목 대비 %
COMPOUND_PCT = 0.15          # AUTO_COMPOUND_PCT
LEVERAGE = 5
TRADE_SD = 1.5               # 건당 손익 표준편차(명목 대비 %) — 신뢰구간 계산용
# 1시간봉 봇은 하루 1~2.8건이라 30일 표본이 29~83건, 검출력 0.8σ로 판정 불가.
# 15분봉 봇만 답을 준다. 보고서에 그 사실을 같이 적는다.
UNDERPOWERED = {"8401", "8409"}

# 동결 기준선 (2026-08-16 12:52, 거래소 원장)
BASELINE = {
    "8401": {"real": -0.5595, "total": 29.55, "w": 5,  "l": 9},
    "8403": {"real": -3.2303, "total": 26.77, "w": 20, "l": 45},
    "8408": {"real": -0.4660, "total": 29.53, "w": 10, "l": 35},
    "8409": {"real": -1.3133, "total": 28.69, "w": 4,  "l": 14},
}


def days_between(a, b):
    fa = time.mktime(time.strptime(a, "%Y-%m-%d"))
    fb = time.mktime(time.strptime(b, "%Y-%m-%d"))
    return int(round((fb - fa) / 86400))


def per_trade(r):
    """건당 손익(명목 대비 %). 거래소 원장 실현손익 ÷ 거래수 ÷ 평균명목.

    평균명목 = 잔고 × 복리비율 × 레버리지. 잔고가 기간 중 변하지만 ±10% 안이라
    현재 잔고로 근사한다(괴리 0.2%p를 다투는 데 영향 없다).
    """
    n = r["wins"] + r["losses"]
    notional = r["total"] * COMPOUND_PCT * LEVERAGE
    if n <= 0 or notional <= 0:
        return None, 0
    return r["real"] / n / notional * 100, n


def gap_line(rows):
    """전 봇 합산 건당 손익과 백테스트 대비 괴리. (문자열, 유의성) 반환."""
    tot_real = sum(r["real"] for _, r, _, _ in rows)
    tot_n = sum(r["wins"] + r["losses"] for _, r, _, _ in rows)
    tot_notional = sum((r["wins"] + r["losses"]) * r["total"] * COMPOUND_PCT * LEVERAGE
                       for _, r, _, _ in rows)
    if tot_n <= 0 or tot_notional <= 0:
        return None, None
    live = tot_real / tot_notional * 100
    gap = live - BACKTEST_PER_TRADE
    se = TRADE_SD / math.sqrt(tot_n)
    sigma = abs(gap) / se if se > 0 else 0.0
    verdict = "괴리 확정" if sigma > 2 else f"판정까지 {int(tot_n*(2/sigma)**2 - tot_n) if sigma > 0 else '?'}건 더"
    return (f"건당 실거래 {live:+.3f}% / 백테 {BACKTEST_PER_TRADE:+.3f}% "
            f"→ 괴리 {gap:+.3f}%p ({sigma:.1f}σ, {tot_n}건) · {verdict}"), sigma


def alive(bot):
    """엔진 프로세스가 살아 있는가."""
    import subprocess
    r = subprocess.run(["pgrep", "-f", f"{BASE}/{bot}/bot.py"],
                       capture_output=True, text=True)
    return bool((r.stdout or "").strip())


def drift():
    """config_sentinel을 점검 전용으로 돌려 어긋난 값이 있는지."""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(HERE, "config_sentinel.py"),
                        "--check-only"], capture_output=True, text=True, timeout=60)
    out = (r.stdout or "") + (r.stderr or "")
    return [l for l in out.splitlines() if "설정" in l and "감지만" in l]


def main():
    import exchange_pnl

    today = time.strftime("%Y-%m-%d")
    elapsed = days_between(FREEZE_START, today)
    left = days_between(today, FREEZE_END)

    rows, tot_real, tot_bal, tot_w, tot_l = [], 0.0, 0.0, 0, 0
    fails = []
    for b in BOTS:
        r = exchange_pnl.fetch_one(b)
        if not r:
            fails.append(b)
            continue
        base = BASELINE[b]
        d_real = r["real"] - base["real"]
        d_trades = (r["wins"] + r["losses"]) - (base["w"] + base["l"])
        rows.append((b, r, d_real, d_trades))
        tot_real += r["real"]
        tot_bal += r["total"]
        tot_w += r["wins"]
        tot_l += r["losses"]

    if not rows:
        return

    pct = (tot_bal - SEED_TOTAL) / SEED_TOTAL * 100
    stop = pct <= STOP_PCT

    L = [f"{'🔴' if stop else '📊'} **[동결 {elapsed}일차 / 30일]**  {time.strftime('%m-%d %H:%M')}",
         f"잔여 {left}일 · 기준선 대비 · 거래소 원장 기준", ""]
    for b, r, d_real, d_tr in rows:
        n = r["wins"] + r["losses"]
        wr = 100 * r["wins"] / n if n else 0
        p = (r["total"] - r["seed"]) / r["seed"] * 100
        mark = "" if alive(b) else "  ⚠️엔진정지"
        pt, _ = per_trade(r)
        pt_s = f"건당 {pt:+.3f}%" if pt is not None else "건당 —"
        low = "  (표본부족)" if b in UNDERPOWERED else ""
        L.append(f"**{b}** {p:+.2f}%  ${r['total']:.2f}  "
                 f"{r['wins']}승{r['losses']}패({wr:.0f}%)  {pt_s}  "
                 f"동결후 {d_real:+.2f} / {d_tr}건{low}{mark}")
    n = tot_w + tot_l
    L += ["",
          f"**합계 {pct:+.2f}%**  ${tot_bal:.2f} / ${SEED_TOTAL:.0f}  "
          f"{tot_w}승{tot_l}패({100*tot_w/n if n else 0:.0f}%)"]

    # 이 동결의 핵심 지표 — 총수익률이 아니라 백테스트와의 괴리
    g, sigma = gap_line(rows)
    if g:
        L += ["", f"🎯 **{g}**"]
        if sigma is not None and sigma > 2:
            L.append("→ 괴리가 확정됐습니다. 원인 추적(미끄러짐·수수료·봇동작·백테낙관)을 시작합니다.")

    if fails:
        L.append(f"⚠️ 조회 실패: {', '.join(fails)}")
    d = drift()
    if d:
        L.append(f"⚠️ 설정 드리프트 감지 {len(d)}건 — 확인 필요")
    if stop:
        L += ["", f"🔴 **중단 조건 도달 ({STOP_PCT:.0f}%)** — 계속할지 판단이 필요합니다."]
    elif elapsed >= 30:
        L += ["", "✅ **30일 동결 종료** — 결과 분석을 시작합니다."]

    msg = "\n".join(L)
    print(msg)
    try:
        from profit_guard import post_discord
        post_discord(msg)
    except Exception as e:
        print(f"(디스코드 전송 실패: {str(e)[:80]})")


if __name__ == "__main__":
    main()
