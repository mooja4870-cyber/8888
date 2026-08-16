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
        L.append(f"**{b}** {p:+.2f}%  ${r['total']:.2f}  "
                 f"{r['wins']}승{r['losses']}패({wr:.0f}%)  "
                 f"동결후 {d_real:+.2f} / {d_tr}건{mark}")
    n = tot_w + tot_l
    L += ["",
          f"**합계 {pct:+.2f}%**  ${tot_bal:.2f} / ${SEED_TOTAL:.0f}  "
          f"{tot_w}승{tot_l}패({100*tot_w/n if n else 0:.0f}%)"]

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
