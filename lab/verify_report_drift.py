#!/usr/bin/env python3
"""verify_report_drift.py — "보고된 성적"과 "실제"의 괴리가 시간이 갈수록 커지는가

가설
────
이번 주에 봇이 실패를 성공으로 보고하는 사례를 5건 찾았고, **전부 좋은 쪽으로**
어긋났다(손익·승패·신호수·보호주문·레버리지). 그렇다면 100개 봇의
"처음엔 좋다가 4~5일 뒤 나빠진다"가 이렇게 설명될 수 있다.

    거래가 쌓일수록 보고와 실제의 괴리가 누적된다
      → 초반에는 괴리가 작아 보고가 그럴듯하다("수익 중")
      → 며칠 지나면 괴리가 커져 실제 잔고가 진실을 드러낸다("갑자기 나빠졌다")

즉 성과가 꺾인 게 아니라 **거짓이 들통나는 데 4~5일이 걸린 것**이라는 가설이다.

검증
────
봇별로 청산 건을 시간순으로 누적하며 두 곡선을 비교한다.
  ① CSV 누적손익   — 대시보드·디스코드가 보여주던 값
  ② 거래소 누적손익 — 실제 (OKX 포지션이력 / 바이낸스 income)
괴리가 거래 수에 비례해 커지면 가설이 성립한다.
"""
import json
import subprocess
import sys

sys.path.insert(0, "/Users/l/project/8888")
import exchange_pnl

BOTS = ["8401", "8403", "8408", "8409"]


def csv_cum(bot, since):
    """CSV 손익·수수료 집계. (청산건수, 손익합, 수수료합)

    수수료는 **모든 행**에서 걷는다. 청산 행만 세면 진입 수수료가 빠져
    CSV가 실제보다 좋아 보인다 — 이 실수로 괴리를 20배 부풀려 보고한 적이 있다
    (8409 실제 +$0.0156을 +$0.3163으로 오보).
    """
    import csv as _csv
    n = 0
    pnl = fee = 0.0
    p = f"/Users/l/project/{bot}/data/trade_history.csv"
    try:
        with open(p, encoding="utf-8-sig") as f:
            for r in _csv.DictReader(f):
                ts = (r.get("시간") or "")[:19]
                if since and ts < since:
                    continue
                try:
                    fee += abs(float(r.get("수수료(USDT)") or 0))
                except ValueError:
                    pass
                if (r.get("유형") or "").strip() != "청산":
                    continue
                try:
                    pnl += float(r.get("수익(USDT)") or 0)
                    n += 1
                except ValueError:
                    continue
    except OSError:
        return 0, 0.0, 0.0
    return n, pnl, fee


def main():
    print("\n  ══ 보고 vs 실제 괴리 ══")
    print("  {:<6}{:>7}{:>13}{:>13}{:>12}{:>12}".format(
        "봇", "청산", "CSV 누적", "거래소 실제", "괴리", "건당 괴리"))
    print("  " + "─" * 64)
    tot_gap = 0.0
    tot_n = 0
    for b in BOTS:
        x = exchange_pnl.get(b, max_age=0)
        if not x:
            print(f"  {b:<6}조회 실패")
            continue
        n, cpnl, cfee = csv_cum(b, x["ps"])
        # CSV는 수수료 차감 전이므로 실제와 맞추려면 수수료를 뺀다
        csv_net = cpnl - cfee
        gap = csv_net - x["real"]
        tot_gap += gap
        tot_n += n
        per = gap / n if n else 0
        print("  {:<6}{:>7}{:>+13.4f}{:>+13.4f}{:>+12.4f}{:>+12.4f}".format(
            b, n, csv_net, x["real"], gap, per))
    print("  " + "─" * 64)
    print("  {:<6}{:>7}{:>26}{:>+12.4f}{:>+12.4f}".format(
        "합계", tot_n, "", tot_gap, tot_gap / tot_n if tot_n else 0))
    print("\n  해석: '건당 괴리'가 0에 가까우면 계측이 건전하다.")
    print("        양수면 거래할수록 실제보다 좋아 보이고, 그 차이가 누적된다.")


if __name__ == "__main__":
    main()
