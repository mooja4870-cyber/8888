#!/usr/bin/env python3
"""verify_pairs.py — 공적분 페어 트레이딩 검증

배경
────
지금까지 검증한 8개 전략은 전부 **방향 예측**이었고 모두 봉인 구간에서 무너졌다.
원인은 상승장 베타 — 오르면 벌고 아니면 잃는 구조였다.

페어 트레이딩은 다르다. 두 코인의 **가격 관계**가 평균으로 돌아오는 데 건다.
한쪽 롱 + 한쪽 숏이라 시장이 오르든 내리든 상관이 적다.
근거: Journal of Futures Markets 2025 — 시총 상위 10개 코인, 2019.1~2024.5,
공적분 기반 페어가 패시브·기존 페어 전략을 일관되게 능가.

방법 (Engle-Granger 2단계)
─────────────────────────
① 개발 구간에서만 회귀 y = a + b·x → 잔차(스프레드) 산출
② 잔차에 ADF 검정 — 정상성이면 공적분 쌍으로 채택
③ 채택된 쌍만 z-점수로 매매: z > +2 → y 숏/x 롱, z < −2 → 반대, |z| < 0.5 청산

**쌍 선정은 개발 구간 데이터만 사용한다.** 봉인 구간을 보고 고르면 미래참조다.
statsmodels가 없어 OLS·ADF를 직접 구현했다(외부 의존 없이 재현 가능하도록).
"""
import glob, itertools, json, os, sys
import numpy as np
import pandas as pd

CACHE = "/Users/l/project/8888/lab_cache_tf"
FEE_LEG = 0.001            # 다리당 왕복 0.1% → 2다리면 0.2%
Z_IN, Z_OUT, Z_STOP = 2.0, 0.5, 4.0
MAX_HOLD = 24 * 7          # 1시간봉 7일
ADF_CRIT = -3.34           # Engle-Granger 5% 임계(2변수, 근사)


def load():
    out = {}
    for p in sorted(glob.glob(f"{CACHE}/1h_*.json")):
        s = os.path.basename(p).split("1h_")[1].split("_USDT")[0]
        df = pd.DataFrame(json.load(open(p)),
                          columns=["ts", "open", "high", "low", "close", "volume"])
        out[s] = df["close"].astype(float).values
    n = min(len(v) for v in out.values())
    return {k: v[-n:] for k, v in out.items()}


def adf_tstat(x, maxlag=4):
    """ADF 검정통계량. Δx_t = α + γ·x_{t-1} + Σβ_i·Δx_{t-i} + ε 에서 γ의 t값.

    statsmodels 없이 최소자승으로 직접 계산한다. γ가 충분히 음수면
    잔차가 평균으로 돌아온다는 뜻이고, 그 쌍은 공적분으로 본다.
    """
    x = np.asarray(x, dtype=float)
    dx = np.diff(x)
    n = len(dx)
    if n < maxlag + 10:
        return 0.0
    y = dx[maxlag:]
    cols = [np.ones(len(y)), x[maxlag:-1]]
    for i in range(1, maxlag + 1):
        cols.append(dx[maxlag - i:-i])
    X = np.column_stack(cols)
    try:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        dof = len(y) - X.shape[1]
        if dof <= 0:
            return 0.0
        s2 = resid @ resid / dof
        xtx_inv = np.linalg.inv(X.T @ X)
        se = np.sqrt(s2 * xtx_inv[1, 1])
        return beta[1] / se if se > 0 else 0.0
    except np.linalg.LinAlgError:
        return 0.0


def hedge_ratio(y, x):
    A = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta[0], beta[1]


def spread(y, x, a, b):
    return y - (a + b * x)


def simulate(sp, lo, hi, mu, sd):
    """z-점수 기반 진입/청산. 손익은 스프레드 변화폭을 진입가 규모로 나눈 비율."""
    if sd <= 0:
        return []
    z = (sp - mu) / sd
    pos, entry_i, entry_sp, out = 0, 0, 0.0, []
    for i in range(lo, hi):
        if pos == 0:
            if z[i] >= Z_IN:
                pos, entry_i, entry_sp = -1, i, sp[i]
            elif z[i] <= -Z_IN:
                pos, entry_i, entry_sp = 1, i, sp[i]
        else:
            hit_stop = abs(z[i]) >= Z_STOP
            hit_out = abs(z[i]) <= Z_OUT
            timeout = (i - entry_i) >= MAX_HOLD
            if hit_stop or hit_out or timeout:
                # 스프레드는 로그가격 차이이므로 변화폭이 곧 조합 포지션의 로그수익률이다.
                # 종전에는 이를 sd로 나눠 'sd 단위'로 만든 값을 %로 표기해
                # +790% 같은 허황된 수치가 나왔다. 나누지 않는다.
                pnl = (sp[i] - entry_sp) * pos
                out.append(pnl - 2 * FEE_LEG)
                pos = 0
    return out


def main():
    px = load()
    n = len(next(iter(px.values())))
    mid = n // 2
    syms = sorted(px)
    print(f"  {len(syms)}종목 · {n}봉(1시간) = {n/24:.0f}일 · 개발=뒤 절반 / 봉인=앞 절반")
    print("  " + "═" * 72)

    # ── 쌍 선정: 개발 구간(뒤 절반)만 사용 ──
    cand = []
    for a, b in itertools.combinations(syms, 2):
        y, x = np.log(px[a][mid:]), np.log(px[b][mid:])
        if not (np.all(np.isfinite(y)) and np.all(np.isfinite(x))):
            continue
        c0, c1 = hedge_ratio(y, x)
        sp = spread(y, x, c0, c1)
        t = adf_tstat(sp)
        if t <= ADF_CRIT:
            cand.append((t, a, b, c0, c1))
    cand.sort()
    npairs = len(syms) * (len(syms) - 1) // 2
    expected_false = npairs * 0.05
    print(f"  개발 구간 공적분 쌍: {len(cand)}개 / 전체 {npairs}쌍")
    print(f"  ※ 5% 유의수준에서 우연히 나올 위양성 기댓값 {expected_false:.1f}개 "
          f"— 실제 {len(cand)}개는 {'그보다 적다(구조 없음)' if len(cand) < expected_false else '기댓값 이상'}")
    for t, a, b, *_ in cand[:8]:
        print(f"    {a}-{b:<10} ADF t={t:.2f}")
    if not cand:
        print("  → 공적분 쌍 없음. 이 방식은 이 데이터에서 성립하지 않는다.")
        return

    # ── 두 구간에서 매매 ──
    print("  " + "─" * 72)
    print(f"  {'구간':<18}{'쌍':>5}{'거래':>7}{'승률':>8}{'순손익':>11}")
    for tag, lo, hi in (("봉인(앞 절반)", 0, mid), ("개발(뒤 절반)", mid, n)):
        tot, wins = [], 0
        for t, a, b, c0, c1 in cand[:10]:
            y, x = np.log(px[a]), np.log(px[b])
            sp = spread(y, x, c0, c1)
            mu, sd = sp[mid:].mean(), sp[mid:].std()   # 기준은 개발 구간에서만
            r = simulate(sp, lo, hi, mu, sd)
            tot += r
        wins = sum(1 for v in tot if v > 0)
        net = sum(tot) * 100
        wr = 100 * wins / len(tot) if tot else 0
        print(f"  {tag:<18}{min(10,len(cand)):>5}{len(tot):>7}{wr:>7.0f}%{net:>+10.1f}%")
    print("  " + "─" * 72)
    print("  손익 = 스프레드 로그변화 − 양다리 수수료 0.2%. 슬리피지·부분체결 미반영(상한값).")


if __name__ == "__main__":
    main()
