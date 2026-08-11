#!/usr/bin/env python3
"""daily_report.py — 4봇 테스트 일일 관찰 리포트

내일 판단할 것이 정해져 있다. 그 판단에 필요한 수치만 뽑는다.

  1) 진입 빈도 — 8408·8409가 계속 0이면 타임프레임(5m/10m)이나 전략을 손봐야 한다.
     기준선: 8408은 5분봉 시절 17건/일, 15분봉 전환 후 7.5건/일.
  2) 게이트 통과율 — 백테스트는 47% 통과였는데 8401 실측은 26%였다.
     실거래가 계속 크게 낮으면 게이트 스팬을 재검토한다.
  3) 수수료 비중 — 8403 첫 거래에서 총수익의 43~53%를 먹었다.
     이 비중이 계속 높으면 '작은 움직임을 자주'가 구조적으로 안 된다는 뜻이다.

수치만 내고 조치는 하지 않는다. 판단은 사람이 한다.
"""
import csv
import datetime
import json
import os
import re
import sys

BASE = "/Users/l/project"
BOTS = ["8401", "8403", "8408", "8409"]


def read_log(bot):
    """엔진 로그와 표준출력 로그를 합쳐 읽는다(봇마다 기록 위치가 갈린다)."""
    out = []
    for name in ("bot_engine.log", "bot_stdout.log"):
        p = os.path.join(BASE, bot, name)
        if os.path.exists(p):
            try:
                out += open(p, encoding="utf-8", errors="ignore").read().splitlines()
            except OSError:
                pass
    return out


def scan_stats(lines):
    scans = sigs = gate = order = 0
    for ln in lines:
        if "[SCAN] 완료" in ln:
            scans += 1
            m = re.search(r"신호 (\d+)개", ln)
            if m:
                sigs += int(m.group(1))
        elif "GATE BLOCK" in ln:
            gate += 1
        elif "ORDER RESULT" in ln and "결과: {" in ln:
            order += 1
    return scans, sigs, gate, order


def trade_stats(bot, since):
    """거래이력에서 청산 건의 손익·수수료를 집계한다."""
    p = os.path.join(BASE, bot, "data", "trade_history.csv")
    if not os.path.exists(p):
        return None
    n = wins = 0
    pnl = fee = 0.0
    try:
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                t = (r.get("시간") or "")[:19]
                try:
                    dt = datetime.datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if dt < since:
                    continue
                try:
                    v = float(r.get("수익(USDT)") or 0)
                    fv = float(r.get("수수료(USDT)") or 0)
                except ValueError:
                    continue
                if v == 0:
                    continue
                n += 1
                wins += v > 0
                pnl += v
                fee += fv
    except OSError:
        return None
    return n, wins, pnl, fee


def main():
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 24.0
    since = datetime.datetime.now() - datetime.timedelta(hours=hours)
    print(f"  ══ 4봇 관찰 리포트 (최근 {hours:.0f}시간) ══")
    print(f"  {'봇':<6}{'스캔':>7}{'신호':>7}{'게이트차단':>11}{'통과율':>8}"
          f"{'진입':>6}{'청산':>6}{'승률':>7}{'손익$':>9}{'수수료비중':>11}")
    print("  " + "─" * 80)
    for b in BOTS:
        scans, sigs, gate, order = scan_stats(read_log(b))
        passed = sigs - gate
        rate = f"{100*passed/sigs:.0f}%" if sigs else "―"
        t = trade_stats(b, since)
        if t:
            n, wins, pnl, fee = t
            wr = f"{100*wins/n:.0f}%" if n else "―"
            fr = f"{100*fee/pnl:.0f}%" if pnl > 0 else "―"
            print(f"  {b:<6}{scans:>7}{sigs:>7}{gate:>11}{rate:>8}"
                  f"{order:>6}{n:>6}{wr:>7}{pnl:>+9.3f}{fr:>11}")
        else:
            print(f"  {b:<6}{scans:>7}{sigs:>7}{gate:>11}{rate:>8}{order:>6}{'―':>6}")
    print("  " + "─" * 80)
    print("  기준선: 8408 진입 7.5건/일(15분봉) · 게이트 통과율 백테스트 47% ·"
          " 수수료비중 40%↑면 구조 재검토")


if __name__ == "__main__":
    main()
