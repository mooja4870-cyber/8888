#!/usr/bin/env python3
"""verify_trade_dependency.py — 승패에 연속성이 있는가 (자기자본곡선 매매의 전제)

왜 이것 하나로 결판나는가
────────────────────────
웹 조사 결과, mooja 봇의 '연패 시 방향 반전'은 정식 명칭이 **Equity Curve Trading**의
역전형이고, 이 계열(끄기형·역전형·반대형·역마팅게일) **전부가 단 하나의 전제**에
의존한다 — **거래 결과에 연속성(serial correlation)이 있는가**.

  · 연속성 양(+): 이기면 또 이긴다 → 역마팅게일·끄기형이 맞다
  · 연속성 음(−): 지면 다음엔 이긴다 → 반대형(연패 후 오히려 크게)이 맞다
  · 연속성 없음:  **계열 전체가 무의미** — 잡음에 반응하며 수수료만 낸다

KJ Trading Systems(실거래·OOS 450거래 × 3전략)의 결론: **"알고 전략 10개 중 9개는
그 연속성이 없다"**. 그리고 5전 3패는 엣지가 0이어도 32% 확률로 그냥 발생한다.

무엇을 재는가
────────────
1. 지연1 자기상관 — 직전 거래 손익과 다음 거래 손익의 상관
2. 조건부 승률 — P(승|직전 승) vs P(승|직전 패). 같으면 연속성 없음
3. **P(승|최근 5건 중 3패 이상)** — 봇의 실제 발동 조건을 그대로 잰다
4. 런 검정(runs test) — 승패 배열이 무작위인지

대상: 8403에 지금 도는 이동평균 20/100 (백테스트 표본이 가장 크다)
      + 실거래 이력(옛 MFI·이중볼린저)도 함께 본다
"""
import csv, os, sys
import numpy as np

sys.path.insert(0, "/Users/l/project/8888/lab")
from verify_ma_expanded import load_daily_aligned, ma_cross, trades, HOLDOUT_DAYS


def dependency(pnl, label):
    """거래 손익 배열의 연속성 지표. 표준오차와 함께 낸다."""
    a = np.array(pnl, dtype=float)
    n = len(a)
    if n < 30:
        print(f"  {label:<28} {n}건 — 표본부족")
        return
    w = (a > 0).astype(int)

    # 1) 지연1 자기상관
    if a[:-1].std() > 0 and a[1:].std() > 0:
        r1 = np.corrcoef(a[:-1], a[1:])[0, 1]
    else:
        r1 = 0.0
    se_r = 1 / np.sqrt(n - 1)

    # 2) 조건부 승률
    pw = w[1:][w[:-1] == 1]
    pl = w[1:][w[:-1] == 0]
    def rate(x):
        return (x.mean(), np.sqrt(max(x.mean() * (1 - x.mean()), 1e-9) / len(x))) if len(x) else (np.nan, np.nan)
    a_w, se_w = rate(pw)
    a_l, se_l = rate(pl)
    diff = a_w - a_l
    se_d = np.sqrt(se_w ** 2 + se_l ** 2) if len(pw) and len(pl) else np.nan

    # 3) 봇의 실제 조건: 최근 5건 중 3패 이상 → 다음 거래 승률
    trig, norm = [], []
    for i in range(5, n):
        losses = int((w[i - 5:i] == 0).sum())
        (trig if losses >= 3 else norm).append(w[i])
    t_m, t_se = rate(np.array(trig)) if trig else (np.nan, np.nan)
    n_m, n_se = rate(np.array(norm)) if norm else (np.nan, np.nan)
    d2 = t_m - n_m
    se2 = np.sqrt(t_se ** 2 + n_se ** 2) if trig and norm else np.nan

    # 4) 런 검정
    runs = 1 + int((w[1:] != w[:-1]).sum())
    n1, n0 = int(w.sum()), int(n - w.sum())
    if n1 and n0:
        mu = 2 * n1 * n0 / n + 1
        var = (mu - 1) * (mu - 2) / (n - 1)
        z = (runs - mu) / np.sqrt(var) if var > 0 else 0.0
    else:
        z = 0.0

    print(f"  {label:<28} {n}건 승률 {100*w.mean():.0f}%")
    print(f"    ① 지연1 자기상관   {r1:+.3f} ± {se_r:.3f}  ({abs(r1)/se_r:.1f}σ)")
    print(f"    ② P(승|직전승) {100*a_w:.1f}%  vs  P(승|직전패) {100*a_l:.1f}%"
          f"   차이 {100*diff:+.1f}%p ± {100*se_d:.1f}  ({abs(diff)/se_d:.1f}σ)")
    print(f"    ③ P(승|5중3패↑) {100*t_m:.1f}% ({len(trig)}건)  vs  평상시 {100*n_m:.1f}% ({len(norm)}건)"
          f"   차이 {100*d2:+.1f}%p ± {100*se2:.1f}  ({abs(d2)/se2:.1f}σ)")
    print(f"    ④ 런 검정 z = {z:+.2f}   {'무작위' if abs(z) < 2 else '무작위 아님'}")
    verdict = "연속성 없음 → 자기자본곡선 계열 전부 무의미"
    if abs(diff) / se_d >= 2 if se_d == se_d else False:
        verdict = "연속성 있음(양)" if diff > 0 else "연속성 있음(음)"
    print(f"    → {verdict}\n")


def live_pnl(bot):
    """실거래 청산 손익 순서대로. 거래소 원장이 아니라 CSV라 부호 판정용으로만 쓴다."""
    p = f"/Users/l/project/{bot}/data/trade_history.csv"
    if not os.path.exists(p):
        return []
    rows = [r for r in csv.DictReader(open(p, encoding="utf-8-sig", errors="ignore"))
            if r.get("유형") == "청산"]
    rows.sort(key=lambda r: r.get("시간", ""))
    out = []
    for r in rows:
        try:
            v = float(r.get("수익(USDT)") or 0)
        except ValueError:
            continue
        if abs(v) > 1e-9:
            out.append(v)
    return out


def main():
    print("  ══ 승패 연속성 검정 ══")
    print("  이 계열(끄기형·역전형·반대형·역마팅게일)은 전부 연속성이 있어야 작동한다.\n")

    frames, N = load_daily_aligned()
    SE = N - HOLDOUT_DAYS
    sm = {s: ma_cross(d, 20, 100) for s, d in frames.items()}
    tr = trades(frames, sm, 0, N, 3.0, 20)
    tr.sort(key=lambda x: x[1])                 # 청산 순서
    dependency([p for _, _, p in tr], "이동평균20/100 (백테 전체)")

    for bot, name in (("8403", "8403 실거래 (옛 MFI)"),
                      ("8408", "8408 실거래 (이중볼린저)"),
                      ("8409", "8409 실거래 (이중볼린저)"),
                      ("8401", "8401 실거래 (MFI)")):
        dependency(live_pnl(bot), name)


if __name__ == "__main__":
    main()
